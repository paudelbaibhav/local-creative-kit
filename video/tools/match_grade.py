"""Bake a .cube LUT that moves a source clip's look toward a reference (Reinhard Lab transfer).

    python tools/match_grade.py --ref references/ref.mp4 --src footage/a.mp4 --name warm_ref
    python tools/match_grade.py --ref references/look.jpg --src footage/ --strength 0.7

--ref / --src accept a video, a photo, or a folder of either; frames are sampled across all
of them. Writes work/luts/<name>.cube (use in an EDL "grade": {"lut": ...}) and prints
before/after/reference look stats so you can judge the match numerically.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

import vtk
from vtk import ROOT, log, probe


def sample_frames(paths: list[Path], n: int = 12) -> list:
    frames = []
    for p in paths:
        if vtk.kind(p) == "image":
            frames.append(vtk.read_frame(p, width=640))
            continue
        d = probe(p)["duration"]
        for t in np.linspace(d * 0.05, d * 0.95, n):
            f = vtk.read_frame(p, float(t), width=640)
            if f is not None:
                frames.append(f)
    return [f for f in frames if f is not None]


def expand(p: Path) -> list[Path]:
    if p.is_dir():
        return sorted(f for f in p.iterdir() if f.suffix.lower() in vtk.IMAGE_EXT | vtk.VIDEO_EXT)
    return [p]


def lab_stats(frames):
    px = np.vstack([cv2.cvtColor(f.astype(np.float32) / 255, cv2.COLOR_BGR2LAB).reshape(-1, 3) for f in frames])
    # trim extremes so specular highlights / letterbox bars don't dominate
    lo, hi = np.percentile(px[:, 0], [1, 99])
    px = px[(px[:, 0] >= lo) & (px[:, 0] <= hi)]
    return px.mean(0), px.std(0) + 1e-6


def transfer(bgr01, sm, ss, rm, rs, strength, max_gain):
    lab = cv2.cvtColor(bgr01.astype(np.float32), cv2.COLOR_BGR2LAB)
    gain = np.clip(rs / ss, 1 / max_gain, max_gain)
    out = (lab - sm) * gain + rm
    out = lab + (out - lab) * strength
    out[..., 0] = np.clip(out[..., 0], 0, 100)
    return np.clip(cv2.cvtColor(out, cv2.COLOR_LAB2BGR), 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--strength", type=float, default=0.85, help="0..1 blend toward the reference")
    ap.add_argument("--max-gain", type=float, default=1.8, help="cap on contrast/chroma stretch")
    ap.add_argument("--size", type=int, default=33)
    a = ap.parse_args()
    ref_f, src_f = sample_frames(expand(a.ref)), sample_frames(expand(a.src))
    if not ref_f or not src_f:
        raise SystemExit("could not read frames")
    rm, rs = lab_stats(ref_f)
    sm, ss = lab_stats(src_f)

    n = a.size
    g = np.linspace(0, 1, n, dtype=np.float32)
    # .cube order: R fastest, then G, then B
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    grid_bgr = np.stack([b, gg, r], -1).reshape(1, -1, 3)
    mapped = transfer(grid_bgr, sm, ss, rm, rs, a.strength, a.max_gain).reshape(-1, 3)

    name = a.name or f"{a.src.stem}_to_{a.ref.stem}"
    dst = ROOT / "work" / "luts" / f"{name}.cube"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="ascii") as fh:
        fh.write(f'TITLE "{name}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for bb, gv, rr in mapped:
            fh.write(f"{rr:.6f} {gv:.6f} {bb:.6f}\n")

    after = [(transfer(f.astype(np.float32) / 255, sm, ss, rm, rs, a.strength, a.max_gain) * 255).astype(np.uint8)
             for f in src_f]
    keys = ["luma_mean", "contrast", "saturation", "warmth", "tint", "black_pt", "white_pt"]
    ref_s = vtk.mean_stats([vtk.frame_stats(f) for f in ref_f])
    src_s = vtk.mean_stats([vtk.frame_stats(f) for f in src_f])
    aft_s = vtk.mean_stats([vtk.frame_stats(f) for f in after])
    print(f"LUT: {dst.relative_to(ROOT).as_posix()}")
    print(f"{'metric':<12}{'source':>10}{'after':>10}{'reference':>11}")
    for k in keys:
        print(f"{k:<12}{src_s[k]:>10}{aft_s[k]:>10}{ref_s[k]:>11}")
    # side-by-side preview: source | graded | reference
    h = 360
    tiles = [cv2.resize(x, (int(x.shape[1] * h / x.shape[0]), h)) for x in (src_f[len(src_f) // 2], after[len(after) // 2], ref_f[len(ref_f) // 2])]
    prev = dst.with_suffix(".preview.jpg")
    vtk.write_image(prev, np.hstack(tiles))
    print(f"preview (source | graded | reference): {prev.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
