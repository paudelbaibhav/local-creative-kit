"""Render an edit decision list (EDL JSON) with ffmpeg.

    python tools/render_edl.py work/edit.json              # full render
    python tools/render_edl.py work/edit.json --preview    # half-res, fast encode, for checking
    python tools/render_edl.py work/edit.json --plan       # only write the timeline map (no render)

Pipeline: every clip -> normalized segment (cached by content hash in work/segments/)
-> join (concat or xfade transitions) -> final pass (overlays, captions, music with
ducking, SFX, fades, loudness normalization). Always writes <output>.timeline.json
mapping each clip to its output time (make_captions.py and qa.py read it).

Schema: see .claude/skills/edit-to-reference/references/edl-schema.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import vtk
from vtk import ROOT, dump, fq, load, log, probe, rel, run

HDR_TRC = {"arib-std-b67", "smpte2084"}
XFADE = {"fade", "fadeblack", "fadewhite", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
         "slideleft", "slideright", "slideup", "slidedown", "smoothleft", "smoothright", "smoothup",
         "smoothdown", "circleopen", "circleclose", "circlecrop", "rectcrop", "distance", "radial",
         "pixelize", "zoomin", "hblur", "fadegrays", "squeezeh", "squeezev", "diagtl", "diagbr",
         "hlslice", "hrslice", "vuslice", "vdslice", "coverleft", "coverright", "revealleft", "revealright"}


def P(path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


# ------------------------------------------------------------------ planning

def plan(edl: dict) -> list[dict]:
    """Resolve durations and output-time placement of every clip."""
    # Every duration is snapped to whole output frames and every in-point to a source frame.
    # Otherwise each segment's video rounds to frames while its audio doesn't, and lip sync
    # drifts a little at every join.
    fps = float(edl.get("fps", 30))
    snap = lambda x, r: round(x * r) / r
    rows, t = [], 0.0
    for i, c in enumerate(edl["clips"]):
        src = P(c["src"])
        k = vtk.kind(src)
        speed = float(c.get("speed", 1.0))
        if k == "image":
            cin = 0.0
            dur = max(snap(float(c.get("duration", 2.0)), fps), 1 / fps)
            src_len = dur
        else:
            info = probe(src)
            src_fps = info.get("fps") or fps
            cin = snap(float(c.get("in", 0.0)), src_fps)
            cout = float(c["out"]) if "out" in c else (cin + float(c["duration"]) * speed if "duration" in c else info["duration"])
            cout = min(cout, info["duration"])
            dur = max(snap((cout - cin) / speed, fps), 1 / fps)
            if cin + dur * speed > info["duration"] + 1e-6:  # never read past the end of the file
                dur = max(int((info["duration"] - cin) / speed * fps) / fps, 1 / fps)
            src_len = dur * speed
        tr = c.get("transition") or {}
        td = float(tr.get("duration", 0)) if i > 0 and tr.get("type", "cut") != "cut" else 0.0
        td = snap(min(td, dur / 2, rows[-1]["dur"] / 2), fps) if rows else 0.0
        start = t - td
        rows.append({"i": i, "src": c["src"], "kind": k, "in": round(cin, 4), "src_len": round(src_len, 4),
                     "speed": speed, "dur": round(dur, 4), "out_start": round(start, 4),
                     "out_end": round(start + dur, 4), "transition": {"type": tr.get("type", "cut"), "duration": td},
                     "label": c.get("label", c.get("text", ""))[:80]})
        t = start + dur
    return rows


# ------------------------------------------------------------------ segment filters

def grade_filters(g: dict | bool | None) -> list[str]:
    if not g:
        return []
    f = []
    if g.get("vf_pre"):
        f.append(g["vf_pre"])
    if "temperature" in g:
        f.append(f"colortemperature=temperature={float(g['temperature'])}:mix={g.get('temperature_mix', 1)}")
    eq = g.get("eq") or {}
    if eq:
        f.append("eq=" + ":".join(f"{k}={v}" for k, v in eq.items()))
    if g.get("curves"):
        cv = g["curves"]
        f.append(f"curves=preset={cv}" if isinstance(cv, str) else "curves=" + ":".join(f"{k}={fq(v)}" for k, v in cv.items()))
    if g.get("colorbalance"):
        f.append("colorbalance=" + ":".join(f"{k}={v}" for k, v in g["colorbalance"].items()))
    if g.get("lut"):
        f.append(f"lut3d=file={fq(rel(P(g['lut'])))}:interp=tetrahedral")
    if g.get("sharpen"):
        f.append(f"unsharp=5:5:{float(g['sharpen'])}:5:5:0")
    if g.get("vignette"):
        ang = g["vignette"] if isinstance(g["vignette"], (int, float)) and g["vignette"] is not True else 0.45
        f.append(f"vignette=angle={ang}")
    if g.get("grain"):
        f.append(f"noise=alls={int(g['grain'])}:allf=t")
    if g.get("vf"):
        f.append(g["vf"])
    return f


def zoom_expr(z: dict, frames: int) -> str:
    a, b = float(z.get("from", 1.0)), float(z.get("to", 1.08))
    p = f"(on/{max(frames - 1, 1)})"
    ease = z.get("ease", "inout")
    if ease == "inout":
        p = f"({p}*{p}*(3-2*{p}))"
    elif ease == "out":
        p = f"(1-(1-{p})*(1-{p}))"
    elif ease == "in":
        p = f"({p}*{p})"
    return f"{a}+({b - a})*{p}"


def segment_cmd(c: dict, row: dict, edl: dict, W: int, H: int, fps: float, out: Path, fast: bool) -> list:
    src = P(c["src"])
    dur = row["dur"]
    cmd = ["ffmpeg", "-y"]
    info = {"has_audio": False}
    if row["kind"] == "image":
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.4f}", "-i", src]
    else:
        info = probe(src)
        cmd += ["-ss", f"{row['in']:.4f}", "-t", f"{row['src_len']:.4f}", "-i", src]
    use_audio = info.get("has_audio") and not c.get("mute")
    if not use_audio:
        cmd += ["-f", "lavfi", "-t", f"{dur:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]

    speed = row["speed"]
    vf = []
    if info.get("color_transfer") in HDR_TRC and c.get("tonemap", True):
        vf.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
                  "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    if speed != 1.0:
        vf.append(f"setpts=(PTS-STARTPTS)/{speed}")
    vf.append(f"fps={fps}")
    fit = c.get("fit", edl.get("fit", "cover"))
    fx, fy = (c.get("focus") or [0.5, 0.5])
    chain = ",".join(vf)
    if fit == "contain":
        geo = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={edl.get('background', 'black')}")
    elif fit == "stretch":
        geo = f"scale={W}:{H}"
    elif fit == "blur":
        geo = None
    else:
        geo = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H}:(iw-{W})*{fx}:(ih-{H})*{fy}")
    g = c.get("grade", edl.get("grade"))
    if isinstance(g, dict) and edl.get("grade") and c.get("grade_merge", True) and c.get("grade") is not None:
        g = {**edl["grade"], **g}
    post = []
    z = c.get("zoom")
    if z:
        frames = max(int(round(dur * fps)), 1)
        post.append(f"scale={W * 2}:{H * 2}:flags=bicubic")
        post.append(f"zoompan=z='{zoom_expr(z, frames)}':d=1:x='(iw-iw/zoom)*{z.get('x', fx)}':"
                    f"y='(ih-ih/zoom)*{z.get('y', fy)}':s={W}x{H}:fps={fps}")
    post += grade_filters(g)
    if c.get("vf"):
        post.append(c["vf"])
    for fd in ("fade_in", "fade_out"):
        if c.get(fd):
            d = float(c[fd])
            post.append(f"fade=t={'in' if fd == 'fade_in' else 'out'}:st={0 if fd == 'fade_in' else max(dur - d, 0):.3f}:d={d}")
    post += ["setsar=1", "format=yuv420p"]
    if geo is None:  # blurred-fill background, sharp contained foreground
        fc = (f"[0:v]{chain},split[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"gblur=sigma={c.get('blur_sigma', 30)},eq=brightness=-0.06[bgb];"
              f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
              f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{','.join(post)}[v]")
    else:
        fc = f"[0:v]{chain},{geo},{','.join(post)}[v]"

    if use_audio:
        af = []
        sp = speed
        while sp > 2.0:
            af.append("atempo=2.0"); sp /= 2.0
        while sp < 0.5:
            af.append("atempo=0.5"); sp /= 0.5
        if sp != 1.0:
            af.append(f"atempo={sp:.5f}")
        af += [f"volume={c.get('volume', 1.0)}", "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
               "afade=t=in:d=0.012", f"apad=whole_dur={dur:.4f}", f"atrim=0:{dur:.4f}",
               f"afade=t=out:st={max(dur - 0.015, 0):.4f}:d=0.015"]
        if c.get("audio_fade_in"):
            af.append(f"afade=t=in:d={c['audio_fade_in']}")
        if c.get("audio_fade_out"):
            af.append(f"afade=t=out:st={max(dur - c['audio_fade_out'], 0):.3f}:d={c['audio_fade_out']}")
        fc += f";[0:a]{','.join(af)}[a]"
    else:
        fc += ";[1:a]anull[a]"
    enc = (["-c:v", "libx264", "-preset", "ultrafast" if fast else "veryfast", "-crf", "24" if fast else "14"])
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", *enc, "-r", str(fps),
            "-c:a", "pcm_s16le", "-ar", "48000", "-t", f"{dur:.4f}", out]
    return cmd


# ------------------------------------------------------------------ join + final

def join(rows: list[dict], segs: list[Path], out: Path, fast: bool):
    if all(r["transition"]["duration"] == 0 for r in rows[1:]):
        lst = out.with_suffix(".concat.txt")
        lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
        return
    cmd = ["ffmpeg", "-y"]
    for s in segs:
        cmd += ["-i", s]
    # xfade needs identical timebases on both inputs; concat outputs AVTB, so put everything on AVTB
    fc = [f"[{k}:v]settb=AVTB[s{k}]" for k in range(len(rows))]
    vlab, alab, acc = "s0", "0:a", rows[0]["dur"]
    for k in range(1, len(rows)):
        r, tr = rows[k], rows[k]["transition"]
        nv, na = f"v{k}", f"a{k}"
        if tr["duration"] > 0:
            ttype = tr["type"] if tr["type"] in XFADE else "fade"
            off = acc - tr["duration"]
            fc.append(f"[{vlab}][s{k}]xfade=transition={ttype}:duration={tr['duration']:.4f}:offset={off:.4f}[{nv}]")
            fc.append(f"[{alab}][{k}:a]acrossfade=d={tr['duration']:.4f}:c1=tri:c2=tri[{na}]")
            acc = off + r["dur"]
        else:
            fc.append(f"[{vlab}][{alab}][s{k}][{k}:a]concat=n=2:v=1:a=1[{nv}][{na}]")
            acc += r["dur"]
        vlab, alab = nv, na
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{vlab}]", "-map", f"[{alab}]",
            "-c:v", "libx264", "-preset", "ultrafast" if fast else "veryfast", "-crf", "24" if fast else "14",
            "-c:a", "pcm_s16le", out]
    run(cmd)


def final(edl: dict, joined: Path, total: float, W: int, H: int, fps: float, out: Path, fast: bool):
    cmd = ["ffmpeg", "-y", "-i", joined]
    n_in = 1
    fc = []
    v = "0:v"
    # overlays (images, alpha video, rendered HyperFrames/Remotion graphics)
    for j, o in enumerate(edl.get("overlays", [])):
        src = P(o["src"])
        st = float(o.get("start", 0))
        en = float(o["end"]) if "end" in o else st + float(o.get("duration", total - st))
        if vtk.kind(src) == "image":
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{en:.3f}", "-i", src]
        else:
            if src.suffix.lower() == ".webm":
                cmd += ["-c:v", "libvpx-vp9"]
            cmd += ["-i", src]
        idx = n_in; n_in += 1
        w = o.get("width")
        scale = f"scale={int(float(w) * W) if w and float(w) <= 1 else int(w)}:-1," if w else ""
        if o.get("fit") == "full":
            scale = f"scale={W}:{H},"
        op = float(o.get("opacity", 1))
        fd = float(o.get("fade", 0))
        chain = f"[{idx}:v]{scale}format=rgba"
        if op < 1:
            chain += f",colorchannelmixer=aa={op}"
        if fd and vtk.kind(src) == "image":
            chain += f",fade=t=in:st={st}:d={fd}:alpha=1,fade=t=out:st={en - fd}:d={fd}:alpha=1"
        if vtk.kind(src) != "image":
            chain += f",setpts=PTS-STARTPTS+{st}/TB"
        fc.append(f"{chain}[ov{j}]")
        pos = {"center": ("(W-w)/2", "(H-h)/2"), "top": ("(W-w)/2", "H*0.08"), "bottom": ("(W-w)/2", "H*0.80-h"),
               "full": ("0", "0")}.get(o.get("position", ""), (o.get("x", "(W-w)/2"), o.get("y", "(H-h)/2")))
        fc.append(f"[{v}][ov{j}]overlay=x={pos[0]}:y={pos[1]}:enable='between(t,{st},{en})':eof_action=pass[vo{j}]")
        v = f"vo{j}"
    vchain = []
    cap = edl.get("captions")
    if cap:
        cap = {"file": cap} if isinstance(cap, str) else cap
        s = f"subtitles=filename={fq(rel(P(cap['file'])))}"
        fdir = P(cap.get("fontsdir", "assets/fonts"))
        if fdir.exists():
            s += f":fontsdir={fq(rel(fdir))}"
        vchain.append(s)
    if edl.get("fade_in"):
        vchain.append(f"fade=t=in:d={edl['fade_in']}")
    if edl.get("fade_out"):
        vchain.append(f"fade=t=out:st={max(total - edl['fade_out'], 0):.3f}:d={edl['fade_out']}")
    vchain.append("format=yuv420p")
    fc.append(f"[{v}]{','.join(vchain)}[vout]")

    # audio
    a = "0:a"
    musics = edl.get("music") or []
    musics = [musics] if isinstance(musics, dict) else musics
    sfx = edl.get("sfx", [])
    mix = []
    n_duck = sum(1 for m in musics if m.get("duck", True))
    if n_duck:
        fc.append(f"[0:a]asplit={n_duck + 1}[voice]" + "".join(f"[sc{d}]" for d in range(n_duck)))
        a = "voice"
    d = 0
    for j, m in enumerate(musics):
        if m.get("loop", True):
            cmd += ["-stream_loop", "-1"]
        if m.get("offset"):
            cmd += ["-ss", str(m["offset"])]
        cmd += ["-i", P(m["src"])]
        idx = n_in; n_in += 1
        st = float(m.get("start", 0))
        ln = float(m.get("end", total)) - st
        fi, fo = float(m.get("fade_in", 0.3)), float(m.get("fade_out", 1.5))
        ch = (f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{ln:.3f},asetpts=PTS-STARTPTS,"
              f"volume={m.get('volume', 0.25)},afade=t=in:d={fi},afade=t=out:st={max(ln - fo, 0):.3f}:d={fo}")
        if st:
            ch += f",adelay={int(st * 1000)}:all=1"
        fc.append(ch + f"[m{j}]")
        if m.get("duck", True):
            fc.append(f"[m{j}][sc{d}]sidechaincompress=threshold={m.get('duck_threshold', 0.02)}:"
                      f"ratio={m.get('duck_ratio', 8)}:attack=15:release={m.get('duck_release', 350)}[md{j}]")
            mix.append(f"md{j}")
            d += 1
        else:
            mix.append(f"m{j}")
    for j, s in enumerate(sfx):
        cmd += ["-i", P(s["src"])]
        idx = n_in; n_in += 1
        ms = int(float(s["at"]) * 1000)
        fc.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={s.get('volume', 0.6)},"
                  f"adelay={ms}:all=1[s{j}]")
        mix.append(f"s{j}")
    achain = []
    if mix:
        labels = "".join(f"[{x}]" for x in [a] + mix)
        fc.append(f"{labels}amix=inputs={1 + len(mix)}:duration=first:normalize=0[amx]")
        a = "amx"
    if edl.get("fade_in"):
        achain.append(f"afade=t=in:d={edl['fade_in']}")
    if edl.get("fade_out"):
        achain.append(f"afade=t=out:st={max(total - edl['fade_out'], 0):.3f}:d={edl['fade_out']}")
    lufs = edl.get("loudness", -14)
    if lufs is not None:
        achain.append(f"loudnorm=I={lufs}:TP=-1.5:LRA=11")
    achain += ["aresample=48000"]
    fc.append(f"[{a}]{','.join(achain)}[aout]")

    if edl.get("encoder") == "nvenc" and not fast:
        venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(edl.get("crf", 19)), "-b:v", "0"]
    else:
        venc = ["-c:v", "libx264", "-preset", "ultrafast" if fast else edl.get("preset", "medium"),
                "-crf", "28" if fast else str(edl.get("crf", 18))]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]", *venc,
            "-pix_fmt", "yuv420p", "-r", str(fps), "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.4f}",
            "-movflags", "+faststart", out]
    run(cmd)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edl", type=Path)
    ap.add_argument("--preview", action="store_true", help="half resolution, fast encode")
    ap.add_argument("--plan", action="store_true", help="write timeline json only")
    a = ap.parse_args()
    edl = load(a.edl)
    out = P(edl.get("output", f"output/{a.edl.stem}.mp4"))
    if a.preview:
        out = out.with_name(out.stem + "_preview.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    W, H, fps = int(edl.get("width", 1080)), int(edl.get("height", 1920)), float(edl.get("fps", 30))
    if a.preview:
        W, H = (W // 2) // 2 * 2, (H // 2) // 2 * 2

    rows = plan(edl)
    total = rows[-1]["out_end"] if rows else 0
    tl = {"edl": str(a.edl), "output": str(out), "width": W, "height": H, "fps": fps,
          "duration": round(total, 4), "clips": rows}
    dump(out.with_suffix(".timeline.json"), tl)
    log(f"{len(rows)} clips → {total:.2f}s at {W}x{H}@{fps}")
    if a.plan:
        print(out.with_suffix(".timeline.json"))
        return

    segdir = ROOT / "work" / "segments"
    segdir.mkdir(parents=True, exist_ok=True)
    segs = []
    gl = {k: edl.get(k) for k in ("grade", "fit", "background")}
    for c, r in zip(edl["clips"], rows):
        src = P(c["src"])
        key = json.dumps([c, r, gl, W, H, fps, a.preview, src.stat().st_mtime, src.stat().st_size], sort_keys=True)
        seg = segdir / f"seg_{hashlib.sha1(key.encode()).hexdigest()[:16]}.mov"
        if not seg.exists():
            log(f"  segment {r['i'] + 1}/{len(rows)}  {Path(c['src']).name} [{r['in']:.2f}+{r['src_len']:.2f}s]")
            run(segment_cmd(c, r, edl, W, H, fps, seg, a.preview))
        segs.append(seg)
    joined = ROOT / "work" / f"_{out.stem}_joined.mov"
    log("  joining ...")
    join(rows, segs, joined, a.preview)
    log("  final pass ...")
    final(edl, joined, total, W, H, fps, out, a.preview)
    info = probe(out)
    log(f"done: {out}  ({info['duration']:.2f}s, {info.get('width')}x{info.get('height')})")
    print(out)


if __name__ == "__main__":
    main()
