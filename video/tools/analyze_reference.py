"""Forensic breakdown of a reference video or photo -> evidence folder + metrics.json + summary.md.

    python tools/analyze_reference.py references/ref.mp4
    python tools/analyze_reference.py references/            # every file in the folder
    python tools/analyze_reference.py ref.mp4 --threshold 22 --model base --no-transcribe

Video output (work/ref_analysis/<stem>/):
  metrics.json      pacing, per-shot look stats, audio stats, palette
  summary.md        human/agent-readable digest -- read this first
  evidence/sheets/  contact sheets (5x4 tiles; timestamp formula in summary.md)
  evidence/shots/   middle frame of every shot (shot_###.jpg)
  evidence/spectrogram.png, waveform.png, transcript.json/.txt
Photo output: metrics.json + summary.md with look stats and palette.

Method adapted from krusemediallc/video-editor-agent reel-style-clone (tools/video-editor-agent).
"""
from __future__ import annotations

import argparse
import math
import re
import statistics
from pathlib import Path

import numpy as np

import vtk
from vtk import ROOT, dump, fmt_ts, log, probe, run


def detect_shots(path: Path, threshold: float, duration: float) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, detect
    scenes = detect(str(path), ContentDetector(threshold=threshold, min_scene_len=6), show_progress=False)
    shots = [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
    return shots or [(0.0, duration)]


def shot_motion(cap, start: float, end: float, samples: int = 5) -> float:
    """Mean abs frame difference across the shot (0..255). High = camera move / action / zooms."""
    import cv2
    ts = np.linspace(start + 0.05, max(start + 0.06, end - 0.05), samples)
    prev, diffs = None, []
    for t in ts:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(f, (160, 160 * f.shape[0] // f.shape[1] or 1)), cv2.COLOR_BGR2GRAY)
        if prev is not None and prev.shape == g.shape:
            diffs.append(float(np.abs(g.astype(np.int16) - prev).mean()))
        prev = g.astype(np.int16)
    return round(statistics.mean(diffs), 2) if diffs else 0.0


def audio_analysis(src: Path, ev: Path, duration: float) -> dict:
    wav = ev / "audio.wav"
    run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
    run(["ffmpeg", "-y", "-i", wav, "-lavfi", "showspectrumpic=s=1920x720:legend=1", ev / "spectrogram.png"])
    run(["ffmpeg", "-y", "-i", wav, "-lavfi", "showwavespic=s=1920x400:colors=0x3a86ff", "-frames:v", "1",
         ev / "waveform.png"])
    out = {}
    p = run(["ffmpeg", "-i", src, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", p.stderr)
    if m:
        out["integrated_lufs"] = float(m[-1])
    if tp:
        out["true_peak_dbfs"] = float(tp[-1])
    p = run(["ffmpeg", "-i", wav, "-af", "silencedetect=n=-38dB:d=0.35", "-f", "null", "-"], check=False)
    sil = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", p.stderr))
    out["silence_ratio"] = round(sil / duration, 3) if duration else 0
    out.update(estimate_tempo(wav))
    return out


def estimate_tempo(wav: Path) -> dict:
    """Spectral-flux onset envelope + autocorrelation. Rough; confirm against the spectrogram."""
    import wave
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if len(x) < sr * 4:
        return {}
    hop, win = 512, 1024
    n = (len(x) - win) // hop
    frames = np.lib.stride_tricks.as_strided(x, (n, win), (x.strides[0] * hop, x.strides[0]))
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
    flux = np.maximum(np.diff(np.log1p(spec), axis=0), 0).sum(axis=1)
    flux -= flux.mean()
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    fps = sr / hop
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    if hi >= len(ac):
        return {}
    lag = lo + int(np.argmax(ac[lo:hi]))
    strength = float(ac[lag] / (ac[0] + 1e-9))
    if 0 < lag < len(ac) - 1:  # parabolic interpolation for sub-frame lag
        y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
        den = y0 - 2 * y1 + y2
        lag = lag + (0.5 * (y0 - y2) / den if den else 0)
    # onset times (for SFX/beat-on-cut checks)
    thr = flux.mean() + 2.0 * flux.std()
    peaks = [i for i in range(1, len(flux) - 1) if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    onsets = [round((i + 1) * hop / sr, 3) for i in peaks]
    return {"tempo_bpm_est": round(60 * fps / lag, 1), "beat_strength": round(strength, 3),
            "strong_onsets": onsets[:400]}


def contact_sheets(src: Path, ev: Path, duration: float, width: int) -> dict:
    sheets = ev / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    for old in sheets.glob("*.png"):
        old.unlink()
    fps = 2.0 if duration <= 120 else max(0.25, round(240 / duration, 3))  # cap at ~12 sheets
    tw = 360 if width <= 1920 else 400
    run(["ffmpeg", "-y", "-i", src, "-vf", f"fps={fps},scale={tw}:-2,tile=5x4:padding=4:color=white",
         sheets / "sheet_%02d.png"])
    return {"fps": fps, "per_sheet_seconds": round(20 / fps, 2), "count": len(list(sheets.glob("*.png")))}


def pacing(shots: list[tuple[float, float]], duration: float) -> dict:
    lens = [e - s for s, e in shots]
    cuts = [s for s, _ in shots[1:]]
    thirds = []
    for i in range(3):
        a, b = duration * i / 3, duration * (i + 1) / 3
        n = sum(1 for c in cuts if a <= c < b)
        thirds.append(round(n / (b - a), 3) if b > a else 0)
    hist = {"<0.5s": 0, "0.5-1s": 0, "1-2s": 0, "2-4s": 0, "4-8s": 0, ">8s": 0}
    for L in lens:
        key = "<0.5s" if L < .5 else "0.5-1s" if L < 1 else "1-2s" if L < 2 else "2-4s" if L < 4 else "4-8s" if L < 8 else ">8s"
        hist[key] += 1
    return {
        "shots": len(shots), "cuts": len(cuts),
        "cuts_per_sec": round(len(cuts) / duration, 3) if duration else 0,
        "shot_len_mean": round(statistics.mean(lens), 3),
        "shot_len_median": round(statistics.median(lens), 3),
        "shot_len_min": round(min(lens), 3), "shot_len_max": round(max(lens), 3),
        "cuts_per_sec_by_third": thirds, "shot_len_histogram": hist,
        "cut_times": [round(c, 3) for c in cuts],
    }


def cuts_on_beats(cut_times: list[float], onsets: list[float], tol: float = 0.08) -> float | None:
    if not cut_times or not onsets:
        return None
    on = np.array(onsets)
    hits = sum(1 for c in cut_times if np.min(np.abs(on - c)) <= tol)
    return round(hits / len(cut_times), 3)


def analyze_video(src: Path, out: Path, a) -> dict:
    import cv2
    info = probe(src)
    dur = info["duration"]
    ev = out / "evidence"
    (ev / "shots").mkdir(parents=True, exist_ok=True)
    for old in (ev / "shots").glob("*.jpg"):
        old.unlink()
    log(f"[{src.name}] {info.get('width')}x{info.get('height')} @ {info.get('fps')}fps, {dur:.1f}s")

    log("  detecting shots ...")
    shots = detect_shots(src, a.threshold, dur)
    pace = pacing(shots, dur)

    log(f"  {len(shots)} shots; sampling look stats ...")
    cap = cv2.VideoCapture(str(src))
    shot_rows, all_stats, pal_frames = [], [], []
    for i, (s, e) in enumerate(shots, 1):
        mid = (s + e) / 2
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        st = vtk.frame_stats(f)
        all_stats.append(st)
        thumb = f if f.shape[1] <= 640 else cv2.resize(f, (640, int(f.shape[0] * 640 / f.shape[1])))
        img = ev / "shots" / f"shot_{i:03d}.jpg"
        vtk.write_image(img, thumb)
        if i % max(1, len(shots) // 12) == 0 or i == 1:
            pal_frames.append(thumb)
        shot_rows.append({"n": i, "start": round(s, 3), "end": round(e, 3), "len": round(e - s, 3),
                          "motion": shot_motion(cap, s, e), **st, "frame": img.relative_to(out).as_posix()})
    cap.release()
    look = vtk.mean_stats(all_stats)
    pal = vtk.palette(np.vstack([cv2.resize(p, (320, 320)) for p in pal_frames])) if pal_frames else []

    log("  contact sheets ...")
    sheets = contact_sheets(src, ev, dur, info.get("width", 1080))

    audio, transcript = {}, None
    if info["has_audio"]:
        log("  audio evidence ...")
        audio = audio_analysis(src, ev, dur)
        audio["cuts_on_onsets_ratio"] = cuts_on_beats(pace["cut_times"], audio.get("strong_onsets", []))
        if not a.no_transcribe:
            log(f"  transcribing (whisper {a.model}) ...")
            transcript = vtk.transcribe(ev / "audio.wav", a.model)
            dump(ev / "transcript.json", transcript)
            (ev / "transcript.txt").write_text(
                "\n".join(f"[{fmt_ts(s['start'])}-{fmt_ts(s['end'])}] {s['text']}" for s in transcript["segments"]),
                encoding="utf-8")
            if transcript["words"] and dur:
                audio["words_per_sec"] = round(len(transcript["words"]) / dur, 2)

    metrics = {"source": info, "pacing": pace, "look_mean": look, "palette": pal,
               "motion_mean": round(statistics.mean(r["motion"] for r in shot_rows), 2) if shot_rows else 0,
               "audio": {k: v for k, v in audio.items() if k != "strong_onsets"},
               "audio_onsets": audio.get("strong_onsets", []), "contact_sheets": sheets, "shots": shot_rows}
    dump(out / "metrics.json", metrics)
    write_summary(out, src, metrics, transcript)
    return metrics


def analyze_image(src: Path, out: Path) -> dict:
    img = vtk.read_frame(src)
    h, w = img.shape[:2]
    metrics = {"source": {"path": str(src), "width": w, "height": h, "aspect": round(w / h, 4)},
               "look_mean": vtk.frame_stats(img), "palette": vtk.palette(img, 6)}
    dump(out / "metrics.json", metrics)
    lm = metrics["look_mean"]
    (out / "summary.md").write_text(
        f"# Reference photo — {src.name}\n\n{w}x{h} (aspect {w/h:.3f})\n\n"
        f"Palette (dominant first): {' '.join(metrics['palette'])}\n\n" + look_table(lm) +
        "\nView the photo itself for composition, typography, and mood — the numbers only cover tone and color.\n",
        encoding="utf-8")
    return metrics


def look_table(lm: dict) -> str:
    def desc():
        out = []
        out.append("bright" if lm["luma_mean"] > 60 else "dark/moody" if lm["luma_mean"] < 38 else "mid-key")
        out.append("high contrast" if lm["contrast"] > 26 else "flat/soft" if lm["contrast"] < 16 else "normal contrast")
        out.append("vivid" if lm["saturation"] > 0.45 else "muted" if lm["saturation"] < 0.22 else "natural saturation")
        out.append("warm" if lm["warmth"] > 6 else "cool" if lm["warmth"] < -3 else "neutral white balance")
        if lm["black_pt"] > 8:
            out.append("lifted/faded blacks")
        if lm["shadow_tint_b"] < -3 and lm["highlight_tint_b"] > 3:
            out.append("teal-shadows / warm-highlights split tone")
        return ", ".join(out)
    rows = "\n".join(f"| {k} | {v} |" for k, v in lm.items())
    return f"**Look:** {desc()}\n\n| metric | value |\n|---|---|\n{rows}\n"


def write_summary(out: Path, src: Path, m: dict, transcript: dict | None):
    s, p, au, cs = m["source"], m["pacing"], m["audio"], m["contact_sheets"]
    lines = [f"# Reference analysis — {src.name}", "",
             f"Source: {s['duration']:.2f}s @ {s.get('width')}x{s.get('height')} {s.get('fps')}fps"
             f" (aspect {s.get('width', 1) / s.get('height', 1):.3f}). Render the edit at the same fps.", "",
             "## Pacing",
             f"- {p['shots']} shots, {p['cuts']} cuts → **{p['cuts_per_sec']} cuts/sec**"
             f" (by thirds: {p['cuts_per_sec_by_third']})",
             f"- shot length mean {p['shot_len_mean']}s · median {p['shot_len_median']}s · "
             f"min {p['shot_len_min']}s · max {p['shot_len_max']}s",
             f"- histogram: {p['shot_len_histogram']}",
             f"- mean in-shot motion {m['motion_mean']} (0 = locked-off still, >12 = handheld/fast action)", "",
             "## Color & grade", f"Palette: {' '.join(m['palette'])}", "", look_table(m["look_mean"]),
             "## Audio"]
    if au:
        lines += [f"- loudness {au.get('integrated_lufs')} LUFS, true peak {au.get('true_peak_dbfs')} dBFS",
                  f"- silence ratio {au.get('silence_ratio')} · words/sec {au.get('words_per_sec', 'n/a')}",
                  f"- tempo estimate {au.get('tempo_bpm_est')} BPM (strength {au.get('beat_strength')};"
                  f" <0.15 means no clear beat — check spectrogram)",
                  f"- cuts landing within 80ms of a strong onset: {au.get('cuts_on_onsets_ratio')}"
                  f" (>0.5 suggests cut-to-beat editing)"]
    else:
        lines.append("- no audio stream")
    lines += ["", "## Evidence to view (in this order)",
              f"1. `evidence/sheets/` — {cs['count']} contact sheets, 5x4 tiles at {cs['fps']} fps; "
              f"sheet N, row r, col c (0-indexed) ≈ t = (N-1)*{cs['per_sheet_seconds']} + (r*5+c)/{cs['fps']} s",
              "2. `evidence/shots/shot_###.jpg` — first look at shots that are outliers in the table below",
              "3. `evidence/spectrogram.png` / `waveform.png` — music bed, SFX spikes, energy arc", ""]
    if transcript:
        lines += ["## Transcript", "```", (out / "evidence" / "transcript.txt").read_text(encoding="utf-8")[:4000], "```", ""]
    lines += ["## Shots", "| # | start | len | motion | luma | contrast | sat | warmth |", "|---|---|---|---|---|---|---|---|"]
    for r in m["shots"]:
        lines.append(f"| {r['n']} | {fmt_ts(r['start'])} | {r['len']:.2f} | {r['motion']} | {r['luma_mean']} | "
                     f"{r['contrast']} | {r['saturation']} | {r['warmth']} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "ref_analysis")
    ap.add_argument("--threshold", type=float, default=27.0, help="PySceneDetect content threshold (lower = more cuts)")
    ap.add_argument("--model", default="small", help="whisper size: tiny/base/small/medium/large-v3")
    ap.add_argument("--no-transcribe", action="store_true")
    a = ap.parse_args()
    files = []
    for i in a.inputs:
        files += sorted(f for f in i.iterdir() if f.is_file() and f.suffix.lower() in vtk.IMAGE_EXT | vtk.VIDEO_EXT) \
            if i.is_dir() else [i]
    for f in files:
        out = a.out / f.stem
        out.mkdir(parents=True, exist_ok=True)
        if vtk.kind(f) == "image":
            analyze_image(f, out)
        else:
            analyze_video(f, out, a)
        print(out / "summary.md")


if __name__ == "__main__":
    main()
