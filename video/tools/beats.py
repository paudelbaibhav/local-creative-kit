"""Beat grid for a music track, so cuts can land on the beat.

    python tools/beats.py assets/music/track.mp3            # -> work/beats/<stem>.json
    python tools/beats.py track.mp3 --every 2 --start 0.5   # print every 2nd beat after 0.5s

JSON: {"bpm", "beats": [...], "downbeats": [...every 4th...], "onsets": [...strong hits...]}.
BPM comes from onset autocorrelation; the grid phase is fitted to the strongest onsets.
Sanity-check by ear/spectrogram — half/double-time errors are possible.
"""
import argparse
from pathlib import Path

import numpy as np

import analyze_reference as ar
from vtk import ROOT, dump, probe, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--bpm", type=float, help="override the detected tempo")
    a = ap.parse_args()
    out = ROOT / "work" / "beats"
    out.mkdir(parents=True, exist_ok=True)
    wav = out / f"{a.src.stem}.wav"
    run(["ffmpeg", "-y", "-i", a.src, "-vn", "-ac", "1", "-ar", "16000", wav])
    t = ar.estimate_tempo(wav)
    dur = probe(wav)["duration"]
    wav.unlink()
    bpm = a.bpm or t.get("tempo_bpm_est")
    if not bpm:
        raise SystemExit("no tempo found (track too short or no clear pulse)")
    onsets = np.array(t.get("strong_onsets", []))
    # jointly refine tempo (±4%) and phase so the most strong onsets sit within 40ms of a beat
    best, phase, period = -1, 0.0, 60 / bpm
    cands = [bpm] if a.bpm else np.arange(bpm * 0.96, bpm * 1.04, 0.05)
    for b in cands:
        per = 60 / b
        for ph in np.linspace(0, per, 48, endpoint=False):
            if not len(onsets):
                break
            d = np.abs(((onsets - ph + per / 2) % per) - per / 2)
            score = float((d < 0.04).sum()) - float(d.mean())  # tie-break on tightness
            if score > best:
                best, phase, period = score, ph, per
    bpm = 60 / period
    best = int(round(best)) if best > 0 else 0
    beats = [round(phase + i * period, 3) for i in range(int((dur - phase) / period) + 1)]
    res = {"src": str(a.src), "duration": round(dur, 3), "bpm": round(bpm, 2), "beat_period": round(period, 4),
           "beats": beats, "downbeats": beats[::4], "onsets": t.get("strong_onsets", []),
           "grid_fit": f"{best}/{len(onsets)} strong onsets on grid"}
    dump(out / f"{a.src.stem}.json", res)
    sel = [b for b in beats if b >= a.start][::a.every]
    print(f"{res['bpm']} BPM, {res['grid_fit']} -> work/beats/{a.src.stem}.json")
    print(" ".join(f"{b:.2f}" for b in sel[:64]))


if __name__ == "__main__":
    main()
