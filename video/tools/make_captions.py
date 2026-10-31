"""Word-timed, styled captions (.ass) for a rendered edit.

    # map source transcripts through the edit (accurate, preferred)
    python tools/make_captions.py --timeline output/final.timeline.json --out work/captions.ass \
        --font "Montserrat" --size 78 --color "#FFFFFF" --highlight "#FFD400" --words 3 --case upper --pop

    # or transcribe the rendered output directly (music-only edits, voiceover added later, etc.)
    python tools/make_captions.py --video output/final_nocaps.mp4 --out work/captions.ass ...

    # style from a JSON preset (keys = the long option names, e.g. {"font": "Inter", "box": "#000000AA"})
    python tools/make_captions.py --timeline ... --preset work/caption_style.json

Then set  "captions": "work/captions.ass"  in the EDL and re-render (segments are cached, so it's quick).
Fonts: drop .ttf/.otf files in assets/fonts/ -- the renderer passes that folder to libass.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import vtk
from vtk import ROOT, load, log


def ass_color(hexstr: str) -> str:
    h = hexstr.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = 255 - int(h[6:8], 16) if len(h) == 8 else 0
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def mapped_words(timeline: dict, tdir: Path) -> list[dict]:
    cache, words = {}, []
    for c in timeline["clips"]:
        if c["kind"] == "image":
            continue
        stem = Path(c["src"]).stem
        if stem not in cache:
            f = tdir / f"{stem}.json"
            cache[stem] = load(f)["words"] if f.exists() else None
            if cache[stem] is None:
                log(f"[warn] no transcript for {c['src']} (run tools/transcribe.py) — its speech gets no captions")
        for w in cache[stem] or []:
            mid = (w["start"] + w["end"]) / 2
            if c["in"] <= mid < c["in"] + c["src_len"]:
                s = c["out_start"] + (max(w["start"], c["in"]) - c["in"]) / c["speed"]
                e = c["out_start"] + (min(w["end"], c["in"] + c["src_len"]) - c["in"]) / c["speed"]
                words.append({"start": s, "end": e, "word": w["word"]})
    words.sort(key=lambda w: w["start"])
    return words


def chunk(words: list[dict], n: int, max_gap: float) -> list[list[dict]]:
    out = []
    for w in words:
        if (out and len(out[-1]) < n and w["start"] - out[-1][-1]["end"] <= max_gap
                and not re.search(r"[.!?]$", out[-1][-1]["word"])):
            out[-1].append(w)
        else:
            out.append([w])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeline", type=Path)
    ap.add_argument("--video", type=Path)
    ap.add_argument("--transcripts", type=Path, default=ROOT / "work" / "transcripts")
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "captions.ass")
    ap.add_argument("--preset", type=Path)
    ap.add_argument("--model", default="small")
    ap.add_argument("--font", default="Arial")
    ap.add_argument("--size", type=int, default=72, help="font px at output height")
    ap.add_argument("--bold", type=int, default=1)
    ap.add_argument("--color", default="#FFFFFF")
    ap.add_argument("--highlight", default=None, help="active-word color (karaoke); omit for none")
    ap.add_argument("--outline-color", default="#000000")
    ap.add_argument("--outline", type=float, default=5)
    ap.add_argument("--shadow", type=float, default=0)
    ap.add_argument("--box", default=None, help="#RRGGBB[AA] background box instead of outline")
    ap.add_argument("--pos", type=float, default=0.70, help="vertical center as fraction of height")
    ap.add_argument("--words", type=int, default=3, help="max words on screen")
    ap.add_argument("--max-gap", type=float, default=0.6)
    ap.add_argument("--case", choices=["asis", "upper", "lower"], default="asis")
    ap.add_argument("--strip-punct", action="store_true")
    ap.add_argument("--pop", action="store_true", help="scale-pop each new chunk")
    ap.add_argument("--spacing", type=float, default=0)
    ap.add_argument("--lead", type=float, default=0.067, help="show each chunk this early (2 frames @30)")
    a = ap.parse_args()
    if a.preset:
        for k, v in load(a.preset).items():
            setattr(a, k.replace("-", "_"), v)

    if a.timeline:
        tl = load(a.timeline)
        W, H = tl["width"], tl["height"]
        words = mapped_words(tl, a.transcripts)
    elif a.video:
        info = vtk.probe(a.video)
        W, H = info["width"], info["height"]
        words = vtk.transcribe(a.video, a.model)["words"]
    else:
        raise SystemExit("need --timeline or --video")
    for w in words:  # captions land a hair before the voice, never after
        w["start"] = max(0.0, w["start"] - a.lead)

    def fmt(w):
        t = w
        if a.strip_punct:
            t = re.sub(r"[^\w'%$#@&-]", "", t)
        return t.upper() if a.case == "upper" else t.lower() if a.case == "lower" else t

    box = a.box is not None
    style = (f"Style: Cap,{a.font},{a.size},{ass_color(a.color)},{ass_color(a.color)},"
             f"{ass_color(a.box if box else a.outline_color)},{ass_color('#00000080')},{-1 if a.bold else 0},0,0,0,100,100,"
             f"{a.spacing},0,{3 if box else 1},{a.outline if not box else 8},{a.shadow},5,40,40,40,1")
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
             "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding", style, "",
             "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    pos = rf"\an5\pos({W // 2},{int(H * a.pos)})"
    hl = ass_color(a.highlight) if a.highlight else None
    chunks = chunk(words, a.words, a.max_gap)
    for ci, ch in enumerate(chunks):
        end = ch[-1]["end"]
        if ci + 1 < len(chunks) and chunks[ci + 1][0]["start"] - end < 0.35:
            end = chunks[ci + 1][0]["start"]
        texts = [fmt(w["word"]).replace("{", "(").replace("}", ")") for w in ch]
        if hl:
            for wi, w in enumerate(ch):
                s = w["start"]
                e = ch[wi + 1]["start"] if wi + 1 < len(ch) else end
                body = " ".join(rf"{{\c{hl}}}{t}{{\r}}" if k == wi else t for k, t in enumerate(texts))
                pop = r"\fscx85\fscy85\t(0,90,\fscx100\fscy100)" if a.pop and wi == 0 else ""
                lines.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{{pos}{pop}}}{body}")
        else:
            pop = r"\fscx85\fscy85\t(0,90,\fscx100\fscy100)" if a.pop else ""
            lines.append(f"Dialogue: 0,{ts(ch[0]['start'])},{ts(end)},Cap,,0,0,0,,{{{pos}{pop}}}{' '.join(texts)}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    log(f"{len(words)} words → {len(chunks)} caption chunks")
    print(a.out)


if __name__ == "__main__":
    main()
