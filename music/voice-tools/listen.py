"""Turn a voice memo into things Claude can read.

Usage:
    .venv/Scripts/python.exe listen.py <audio file> [--model small] [--no-melody] [--no-words]

Writes to out/<memo name>/:
    transcript.txt  - what you said or sang (Whisper)
    melody.mid      - the notes you hummed/sang (Basic Pitch)
    summary.txt     - key, tempo, note list, and transcript in one readable file
"""
import argparse
import sys
from pathlib import Path

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler key profiles
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def transcribe(audio: Path, model_size: str) -> str:
    from faster_whisper import WhisperModel

    # CPU keeps the GPU free for ACE-Step
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), vad_filter=True)
    lines = [f"[{s.start:6.1f}s] {s.text.strip()}" for s in segments]
    header = f"(language: {info.language}, confidence {info.language_probability:.0%})"
    return header + "\n" + "\n".join(lines)


def estimate_key(notes) -> str:
    import numpy as np

    hist = np.zeros(12)
    for n in notes:
        hist[n.pitch % 12] += n.end - n.start
    if hist.sum() == 0:
        return "unknown"
    best, best_score = "unknown", -2.0
    for tonic in range(12):
        for name, profile in (("major", MAJOR), ("minor", MINOR)):
            score = np.corrcoef(hist, np.roll(profile, tonic))[0, 1]
            if score > best_score:
                best, best_score = f"{NOTE_NAMES[tonic]} {name}", score
    return f"{best} (confidence {best_score:.2f})"


def estimate_tempo(audio: Path) -> str:
    import librosa

    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(tempo[0] if hasattr(tempo, "__len__") else tempo)
    return f"~{tempo:.0f} BPM (rough; humming has weak beats)"


def extract_melody(audio: Path, out_dir: Path):
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    _, midi, _ = predict(str(audio), ICASSP_2022_MODEL_PATH)
    midi.write(str(out_dir / "melody.mid"))
    notes = sorted(
        (n for inst in midi.instruments for n in inst.notes if n.end - n.start >= 0.08),
        key=lambda n: n.start,
    )
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("--model", default="small", help="Whisper size: tiny, base, small, medium")
    ap.add_argument("--no-melody", action="store_true")
    ap.add_argument("--no-words", action="store_true")
    args = ap.parse_args()

    if not args.audio.exists():
        sys.exit(f"File not found: {args.audio}")

    out_dir = Path(__file__).parent / "out" / args.audio.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = [f"Memo: {args.audio.name}", ""]

    if not args.no_words:
        print("Transcribing words...", flush=True)
        text = transcribe(args.audio, args.model)
        (out_dir / "transcript.txt").write_text(text, encoding="utf-8")
        summary += ["== Words ==", text, ""]

    if not args.no_melody:
        print("Extracting melody...", flush=True)
        notes = extract_melody(args.audio, out_dir)
        summary += [
            "== Melody ==",
            f"Key:   {estimate_key(notes)}",
            f"Tempo: {estimate_tempo(args.audio)}",
            f"Notes: {len(notes)} (full detail in melody.mid)",
            "",
            "start   dur    note",
        ]
        for n in notes[:200]:
            name = f"{NOTE_NAMES[n.pitch % 12]}{n.pitch // 12 - 1}"
            summary.append(f"{n.start:6.2f}s {n.end - n.start:5.2f}s  {name}")
        if len(notes) > 200:
            summary.append(f"... {len(notes) - 200} more")

    (out_dir / "summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"Done -> {out_dir}")


if __name__ == "__main__":
    main()
