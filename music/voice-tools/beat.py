"""Turn a beatboxed / tapped / recorded beat into a drum grid Claude can read.

Usage:
    .venv/Scripts/python.exe beat.py <audio file> [--bpm 90]

Writes out/<memo name>/beat.txt and beat.mid (General MIDI drums).
Hits are sorted into kick / snare / hat by where their energy sits in the spectrum,
so it works for beatboxing, table taps, or a beat played from a speaker.
"""
import argparse
import warnings
from pathlib import Path

import librosa
import numpy as np

warnings.filterwarnings("ignore")

SR = 22050
GM = {"kick": 36, "snare": 38, "hat": 42}


def classify(y, sr, onset_samples):
    """Label each onset by its spectral balance in the first 80ms.

    Thresholds are relative to the memo's own hits: phone mics cut most of the
    low end, so a beatboxed kick may only carry ~20% bass. The bassiest hits are
    kicks, the brightest are hats, the rest snares.
    """
    win = int(0.08 * sr)
    feats = []
    for s in onset_samples:
        seg = y[s : s + win]
        if len(seg) < win // 2:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / sr)
        total = spec.sum() + 1e-9
        low = spec[freqs < 250].sum() / total
        centroid = (spec * freqs).sum() / total
        strength = float(np.sqrt(np.mean(seg**2)))
        feats.append((s / sr, low, centroid, strength))
    if not feats:
        return []
    lows = np.array([f[1] for f in feats])
    cents = np.array([f[2] for f in feats])
    kick_cut = max(0.15, np.percentile(lows, 70))
    hat_cut = np.percentile(cents, 70)
    hits = []
    for t, low, centroid, strength in feats:
        if low >= kick_cut and low > 1.5 * np.median(lows):
            label = "kick"
        elif centroid >= hat_cut and low < np.median(lows):
            label = "hat"
        else:
            label = "snare"
        hits.append((t, label, strength, centroid))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--bpm", type=float, help="override detected tempo")
    ap.add_argument("--start", type=float, default=0.0, help="skip the first N seconds (e.g. talking)")
    args = ap.parse_args()

    y, sr = librosa.load(str(args.audio), sr=SR, mono=True, offset=args.start)
    y = y / (np.max(np.abs(y)) + 1e-9)  # quiet phone memos: normalize before analysis
    out_dir = Path(__file__).parent / "out" / args.audio.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # How much of the sound is percussive vs tonal
    harm, perc = librosa.effects.hpss(y)
    perc_share = float(np.sum(perc**2) / (np.sum(harm**2) + np.sum(perc**2) + 1e-9))

    onset_env = librosa.onset.onset_strength(y=perc, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True, units="samples")
    hits = classify(y, sr, onsets)
    if hits:  # drop faint hits (breaths, room noise)
        loud = max(h[2] for h in hits)
        hits = [h for h in hits if h[2] > 0.12 * loud]

    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    bpm = args.bpm or float(np.atleast_1d(tempo)[0])
    # Hand-made beats often read at double/half time; keep it in a musical range
    while bpm > 160:
        bpm /= 2
    while bpm < 65:
        bpm *= 2

    lines = [
        f"Beat memo: {args.audio.name}  ({len(y) / sr:.1f}s analysed, from {args.start:.1f}s; times below are from there)",
        f"Percussive share of sound: {perc_share:.0%}"
        + ("  (mostly beat)" if perc_share > 0.5 else "  (lots of tonal/vocal content too)"),
        f"Tempo: ~{bpm:.0f} BPM",
        f"Hits kept: {len(hits)}  (kick {sum(h[1] == 'kick' for h in hits)}, "
        f"snare {sum(h[1] == 'snare' for h in hits)}, hat {sum(h[1] == 'hat' for h in hits)})",
        "",
    ]

    if hits:
        # 16th-note grid, starting at the first hit
        step = 60 / bpm / 4
        t0 = hits[0][0]
        n_steps = int(np.ceil((hits[-1][0] - t0) / step)) + 1
        n_bars = int(np.ceil(n_steps / 16))
        grid = {k: ["."] * (n_bars * 16) for k in ("hat", "snare", "kick")}
        offsets = []
        for t, label, strength, _ in hits:
            idx = int(round((t - t0) / step))
            offsets.append((t - t0) / step - idx)
            if idx < len(grid[label]):
                grid[label][idx] = "X" if strength > 0.5 * max(h[2] for h in hits) else "x"
        timing = float(np.mean(np.abs(offsets))) * 100
        lines.append(f"Grid: 16th notes, X = loud, x = soft. Timing looseness: {timing:.0f}% of a 16th")
        lines.append("")
        for b in range(n_bars):
            lines.append(f"Bar {b + 1}   |1 . . . 2 . . . 3 . . . 4 . . . |")
            for k in ("hat", "snare", "kick"):
                cells = grid[k][b * 16 : (b + 1) * 16]
                lines.append(f"  {k:<6}|" + " ".join(cells) + " |")
            lines.append("")

        lines.append("Hit list (time, type, loudness, brightness Hz):")
        for t, label, strength, centroid in hits:
            lines.append(f"  {t:6.2f}s  {label:<5}  {strength:.3f}  {centroid:6.0f}")

        import pretty_midi

        pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        drums = pretty_midi.Instrument(program=0, is_drum=True)
        loud = max(h[2] for h in hits)
        for t, label, strength, _ in hits:
            vel = int(50 + 77 * min(1.0, strength / loud))
            drums.notes.append(pretty_midi.Note(vel, GM[label], t - t0, t - t0 + 0.1))
        pm.instruments.append(drums)
        pm.write(str(out_dir / "beat.mid"))

    (out_dir / "beat.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
