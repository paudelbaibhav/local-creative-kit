"""Talking-head rough cut: keep speech, drop dead air and filler words -> EDL clips.

    python tools/speech_edl.py footage/a.mp4 --max-gap 0.35 --pad 0.08 > work/a_clips.json

Reads work/transcripts/<stem>.json (run transcribe.py first). Output is a JSON list of
clip objects ready to paste into an EDL's "clips" array (render_edl.py). Each clip
carries "text" so you can reorder or delete lines by content.
"""
import argparse
import json
import re
from pathlib import Path

from vtk import ROOT, load, probe

FILLERS = {"um", "uh", "erm", "uhm", "hmm", "mm", "ah", "eh"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--transcript", type=Path)
    ap.add_argument("--max-gap", type=float, default=0.35, help="pauses longer than this are cut")
    ap.add_argument("--pad", type=float, default=0.08, help="breathing room kept around speech")
    ap.add_argument("--min-clip", type=float, default=0.4)
    ap.add_argument("--keep-fillers", action="store_true")
    ap.add_argument("--filler-gap", type=float, default=0.12, help="silence needed on both sides to drop a filler")
    a = ap.parse_args()
    t = load(a.transcript or ROOT / "work" / "transcripts" / f"{a.src.stem}.json")
    dur = probe(a.src)["duration"]
    # Drop a filler only when it is isolated by silence on both sides; one that runs straight
    # into the next word stays, because cutting it clips the neighbours (herk-edit-kit playbook).
    allw = t["words"]
    words = []
    for i, w in enumerate(allw):
        is_filler = re.sub(r"[^a-z]", "", w["word"].lower()) in FILLERS
        gap_before = w["start"] - allw[i - 1]["end"] if i else 9
        gap_after = allw[i + 1]["start"] - w["end"] if i + 1 < len(allw) else 9
        if is_filler and not a.keep_fillers and gap_before >= a.filler_gap and gap_after >= a.filler_gap:
            continue
        words.append(w)
    groups = []
    for w in words:
        if groups and w["start"] - groups[-1][-1]["end"] <= a.max_gap:
            groups[-1].append(w)
        else:
            groups.append([w])
    clips = []
    for g in groups:
        s, e = max(0, g[0]["start"] - a.pad), min(dur, g[-1]["end"] + a.pad)
        if clips and s <= clips[-1]["out"]:
            clips[-1]["out"] = round(e, 3)
            clips[-1]["text"] += " " + " ".join(w["word"] for w in g)
            continue
        if e - s >= a.min_clip:
            clips.append({"src": Path(a.src).as_posix(), "in": round(s, 3), "out": round(e, 3),
                          "text": " ".join(w["word"] for w in g)})
    kept = sum(c["out"] - c["in"] for c in clips)
    print(json.dumps(clips, indent=2, ensure_ascii=False))
    import sys
    print(f"# {len(clips)} clips, kept {kept:.1f}s of {dur:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
