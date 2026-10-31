"""QA a rendered edit: technical checks + how close it is to the reference's pacing and look.

    python tools/qa.py output/final.mp4 --ref work/ref_analysis/ref/metrics.json

Writes work/qa/<stem>/qa-report.md and contact sheets of the render (view them!).
Exit code 0 PASS, 1 PASS_WITH_WARNINGS, 2 FAIL.
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

import cv2

import analyze_reference as ar
import vtk
from vtk import ROOT, load, log, probe, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--ref", type=Path, help="metrics.json from analyze_reference.py")
    ap.add_argument("--timeline", type=Path)
    ap.add_argument("--target-lufs", type=float, default=-14)
    a = ap.parse_args()
    v = a.video
    out = ROOT / "work" / "qa" / v.stem
    out.mkdir(parents=True, exist_ok=True)
    info = probe(v)
    dur = info["duration"]
    issues = []  # (severity, message)

    tl_path = a.timeline or v.with_suffix(".timeline.json")
    tl = None
    if tl_path.exists():
        tl = load(tl_path)
        if abs(tl["duration"] - dur) > 0.25:
            issues.append(("HIGH", f"duration {dur:.2f}s differs from planned {tl['duration']:.2f}s"))
    if not info["has_audio"]:
        issues.append(("CRITICAL", "no audio stream"))
    else:
        p = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", v])
        sd = {}
        for line in p.stdout.split():
            parts = line.split(",")
            if len(parts) == 2 and parts[1] not in ("", "N/A"):
                sd.setdefault(parts[0], float(parts[1]))
        if "video" in sd and "audio" in sd and abs(sd["video"] - sd["audio"]) > 1.5 / (info.get("fps") or 30):
            issues.append(("HIGH", f"audio {sd['audio']:.3f}s vs video {sd['video']:.3f}s — A/V length mismatch (sync drift?)"))

    p = run(["ffmpeg", "-i", v, "-vf", "blackdetect=d=0.1:pix_th=0.08", "-an", "-f", "null", "-"], check=False)
    for s, e in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr):
        s, e = float(s), float(e)
        sev = "LOW" if s < 0.05 or e > dur - 0.1 else "HIGH"  # fades at head/tail are fine
        issues.append((sev, f"black frames {s:.2f}-{e:.2f}s"))
    p = run(["ffmpeg", "-i", v, "-vf", "freezedetect=n=0.003:d=0.6", "-an", "-f", "null", "-"], check=False)
    for s, d in re.findall(r"freeze_start: ([\d.]+).*?freeze_duration: ([\d.]+)", p.stderr, re.S):
        issues.append(("MEDIUM", f"frozen picture {float(s):.2f}s for {float(d):.2f}s (intended still? give it motion)"))
    if info["has_audio"]:
        p = run(["ffmpeg", "-i", v, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
        lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
        tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", p.stderr)
        lufs = float(lufs[-1]) if lufs else None
        tp = float(tp[-1]) if tp else None
        if lufs is not None and abs(lufs - a.target_lufs) > 2:
            issues.append(("MEDIUM", f"loudness {lufs} LUFS (target {a.target_lufs})"))
        if tp is not None and tp > -0.5:
            issues.append(("HIGH", f"true peak {tp} dBFS — clipping risk"))
        p = run(["ffmpeg", "-i", v, "-vn", "-af", "silencedetect=n=-45dB:d=0.7", "-f", "null", "-"], check=False)
        for s, d in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)", p.stderr):
            issues.append(("MEDIUM", f"dead air {float(s):.2f}s for {float(d):.2f}s"))
    else:
        lufs = tp = None

    shots = ar.detect_shots(v, 27.0, dur)
    pace = ar.pacing(shots, dur)
    if tl and len(tl["clips"]) > len(shots):
        # jump cuts within the same angle are invisible to scene detection; trust the edit's own plan
        planned = [(c["out_start"], c["out_end"]) for c in tl["clips"]]
        pace = ar.pacing(planned, dur)
        pace["note"] = "pacing from timeline (planned cuts); scene detection saw " + str(len(shots))
    cap = cv2.VideoCapture(str(v))
    stats = []
    for s, e in shots:
        cap.set(cv2.CAP_PROP_POS_MSEC, (s + e) / 2 * 1000)
        ok, f = cap.read()
        if ok:
            stats.append(vtk.frame_stats(f))
    cap.release()
    look = vtk.mean_stats(stats)
    sheets = ar.contact_sheets(v, out, dur, info.get("width", 1080))

    cmp_rows = []
    if a.ref:
        ref = load(a.ref)
        rp, rl = ref.get("pacing"), ref["look_mean"]
        if rp:
            for k in ("cuts_per_sec", "shot_len_median", "shot_len_min", "shot_len_max"):
                cmp_rows.append((k, pace[k], rp[k]))
            if rp["cuts_per_sec"] and abs(pace["cuts_per_sec"] - rp["cuts_per_sec"]) / rp["cuts_per_sec"] > 0.2:
                issues.append(("MEDIUM", f"pacing {pace['cuts_per_sec']} cuts/s vs reference {rp['cuts_per_sec']} (>20% off)"))
        tol = {"luma_mean": 6, "contrast": 4, "saturation": 0.06, "warmth": 3, "tint": 3, "black_pt": 4, "white_pt": 5}
        for k, t in tol.items():
            cmp_rows.append((k, look.get(k), rl.get(k)))
            if k in look and k in rl and abs(look[k] - rl[k]) > t:
                issues.append(("MEDIUM", f"look: {k} {look[k]} vs reference {rl[k]} (tolerance ±{t})"))
        ra = ref.get("source", {})
        if ra.get("width") and abs(ra["width"] / ra["height"] - info["width"] / info["height"]) > 0.02:
            issues.append(("HIGH", f"aspect {info['width']}x{info['height']} differs from reference {ra['width']}x{ra['height']}"))
        if ra.get("fps") and abs(ra["fps"] - info.get("fps", 0)) > 0.5:
            issues.append(("LOW", f"fps {info.get('fps')} vs reference {ra['fps']}"))

    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    issues.sort(key=lambda x: rank[x[0]])
    sev = {s for s, _ in issues}
    verdict = "FAIL" if sev & {"CRITICAL", "HIGH"} else "PASS_WITH_WARNINGS" if "MEDIUM" in sev else "PASS"
    md = [f"# QA — {v.name}: **{verdict}**", "",
          f"{dur:.2f}s · {info.get('width')}x{info.get('height')} @ {info.get('fps')}fps · "
          f"{lufs} LUFS · TP {tp} dBFS · {pace['shots']} shots ({pace['cuts_per_sec']} cuts/s)", "",
          "## Issues"] + ([f"- **{s}** {m}" for s, m in issues] or ["- none"])
    if cmp_rows:
        md += ["", "## Render vs reference", "| metric | render | reference |", "|---|---|---|"]
        md += [f"| {k} | {r} | {f} |" for k, r, f in cmp_rows]
    md += ["", f"## Contact sheets\n`{(out / 'sheets').relative_to(ROOT).as_posix()}/` — "
           f"{sheets['count']} sheets at {sheets['fps']} fps. Look at them next to the reference sheets."]
    (out / "qa-report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    sys.exit({"PASS": 0, "PASS_WITH_WARNINGS": 1, "FAIL": 2}[verdict])


if __name__ == "__main__":
    main()
