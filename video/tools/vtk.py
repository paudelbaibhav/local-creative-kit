"""Shared helpers for the video toolkit (ffmpeg/ffprobe, whisper, frame stats).

Every tool in this folder imports from here. Paths handed to ffmpeg filters
(LUTs, subtitles, fonts) are made relative to the project root so Windows
drive-letter colons never need filtergraph escaping.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the video/ project root
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def run(cmd: list, cwd: Path | None = None, check=True, quiet=True) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    if cmd[0] in ("ffmpeg", "ffprobe") and "-hide_banner" not in cmd:
        cmd.insert(1, "-hide_banner")
    p = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:12])} ...\n{tail}")
    if not quiet:
        log(p.stderr)
    return p


def kind(path: Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    return "video"


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    data = json.loads(p.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {"path": str(path), "duration": float(data["format"].get("duration") or 0),
            "has_audio": a is not None, "has_video": v is not None}
    if v:
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) in (90, 270):
            w, h = h, w
        info.update(width=w, height=h, fps=round(fps, 3), vcodec=v.get("codec_name"),
                    pix_fmt=v.get("pix_fmt"), color_transfer=v.get("color_transfer"))
    if a:
        info.update(acodec=a.get("codec_name"), sample_rate=int(a.get("sample_rate", 0)),
                    channels=a.get("channels"))
    return info


def rel(path: Path | str) -> str:
    """Project-root-relative posix path for use inside ffmpeg filter arguments."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        tmp = ROOT / "work" / "_filterfiles"
        tmp.mkdir(parents=True, exist_ok=True)
        dst = tmp / path.name
        shutil.copy2(path, dst)
        return dst.relative_to(ROOT).as_posix()


def fq(s: str) -> str:
    """Quote a value for an ffmpeg filter option."""
    return "'" + s.replace("'", r"'\''") + "'"


# ---------------------------------------------------------------- whisper

_MODEL = {}


def whisper_model(size: str = "small"):
    if size in _MODEL:
        return _MODEL[size]
    from faster_whisper import WhisperModel
    try:
        m = WhisperModel(size, device="cuda", compute_type="float16")
        m._vtk_device = "cuda"
    except Exception:
        m = WhisperModel(size, device="cpu", compute_type="int8")
        m._vtk_device = "cpu"
    _MODEL[size] = m
    return m


def transcribe(media: Path, size: str = "small", language: str | None = None) -> dict:
    """Word-level transcript. Falls back to CPU if the CUDA libs are missing at decode time."""
    import numpy as np
    # decode with ffmpeg ourselves (16k mono f32) — sidesteps PyAV version breakage in faster-whisper
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32).copy()

    def _do(model):
        segs, info = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                      language=language, beam_size=5)
        # "text"/"audio_duration_secs" make this the common format herk-edit-kit's cutters read
        out = {"language": info.language, "duration": info.duration,
               "audio_duration_secs": round(len(audio) / 16000, 3), "segments": [], "words": []}
        for s in segs:
            out["segments"].append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
            for w in s.words or []:
                out["words"].append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip(),
                                     "text": w.word.strip(), "type": "word", "p": round(w.probability, 3)})
        out["text"] = " ".join(s["text"] for s in out["segments"])
        return out
    model = whisper_model(size)
    try:
        return _do(model)
    except Exception as e:
        if getattr(model, "_vtk_device", "") != "cuda":
            raise
        log(f"[whisper] CUDA failed ({e.__class__.__name__}); retrying on CPU")
        from faster_whisper import WhisperModel
        model = WhisperModel(size, device="cpu", compute_type="int8")
        model._vtk_device = "cpu"
        _MODEL[size] = model
        return _do(model)


def fmt_ts(t: float) -> str:
    m, s = divmod(max(t, 0), 60)
    return f"{int(m):02d}:{s:05.2f}"


# ---------------------------------------------------------------- frame stats

def frame_stats(bgr) -> dict:
    """Look metrics for one frame (BGR uint8). Units chosen to be comparable across clips."""
    import cv2
    import numpy as np
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0] * (100 / 255)
    a = lab[..., 1] - 128
    b = lab[..., 2] - 128
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(np.float32) / 255
    chroma = np.sqrt(a * a + b * b)
    return {
        "luma_mean": round(float(L.mean()), 2),          # 0..100
        "contrast": round(float(L.std()), 2),             # L* std
        "black_pt": round(float(np.percentile(L, 1)), 2),
        "white_pt": round(float(np.percentile(L, 99)), 2),
        "saturation": round(float(sat.mean()), 3),        # 0..1
        "chroma": round(float(chroma.mean()), 2),
        "warmth": round(float(b.mean()), 2),              # +yellow/-blue
        "tint": round(float(a.mean()), 2),                # +magenta/-green
        "shadow_tint_b": round(float(b[L < 25].mean()) if (L < 25).any() else 0.0, 2),
        "highlight_tint_b": round(float(b[L > 75].mean()) if (L > 75).any() else 0.0, 2),
    }


def palette(bgr, k: int = 5) -> list[str]:
    import cv2
    import numpy as np
    small = cv2.resize(bgr, (96, int(96 * bgr.shape[0] / bgr.shape[1]) or 1))
    px = small.reshape(-1, 3).astype(np.float32)
    k = min(k, len(px))
    _, labels, centers = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                                    3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    return ["#%02x%02x%02x" % tuple(int(c) for c in centers[i][::-1]) for i in order]


def read_frame(path: Path, t: float | None = None, width: int | None = None):
    import cv2
    if kind(path) == "image":
        import numpy as np
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    else:
        cap = cv2.VideoCapture(str(path))
        if t is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        cap.release()
        if not ok:
            return None
    if img is not None and width and img.shape[1] > width:
        img = cv2.resize(img, (width, int(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
    return img


def write_image(path: Path, img):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".jpg", img)
    buf.tofile(str(path))


def mean_stats(stats: list[dict]) -> dict:
    if not stats:
        return {}
    keys = stats[0].keys()
    return {k: round(sum(s[k] for s in stats) / len(stats), 3) for k in keys}


def dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
