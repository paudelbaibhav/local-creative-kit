"""Word-level transcripts for footage (local faster-whisper, GPU if available).

    python tools/transcribe.py footage/                 # all clips -> work/transcripts/<stem>.json/.txt
    python tools/transcribe.py footage/a.mp4 --model medium --language en
"""
import argparse
from pathlib import Path

import vtk
from vtk import ROOT, dump, fmt_ts, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--model", default="small")
    ap.add_argument("--language", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "transcripts")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    files = []
    for i in a.inputs:
        files += sorted(f for f in i.iterdir() if f.suffix.lower() in vtk.VIDEO_EXT | vtk.AUDIO_EXT) if i.is_dir() else [i]
    for f in files:
        dst = a.out / f"{f.stem}.json"
        if dst.exists() and not a.force:
            print(dst)
            continue
        if vtk.kind(f) == "video" and not vtk.probe(f)["has_audio"]:
            log(f"[skip] {f.name}: no audio")
            continue
        log(f"[whisper {a.model}] {f.name}")
        t = vtk.transcribe(f, a.model, a.language)
        t["source"] = str(f)
        dump(dst, t)
        dst.with_suffix(".txt").write_text(
            "\n".join(f"[{fmt_ts(s['start'])}-{fmt_ts(s['end'])}] {s['text']}" for s in t["segments"]), encoding="utf-8")
        print(dst)


if __name__ == "__main__":
    main()
