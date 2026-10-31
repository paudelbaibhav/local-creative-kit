# EDL schema (tools/render_edl.py)

Paths are relative to the project root (the `video/` folder). Times in seconds.

```jsonc
{
  "output": "output/reel_v1.mp4",
  "width": 1080, "height": 1920, "fps": 30,     // match the reference
  "fit": "cover",                                // default for clips: cover | contain | blur | stretch
  "background": "black",                         // pad color for contain
  "grade": {                                     // global grade, applied to every clip
    "lut": "work/luts/job_main.cube",
    "eq": {"contrast": 1.05, "saturation": 1.1, "brightness": 0.0, "gamma": 1.0},
    "temperature": 6000,                         // Kelvin, colortemperature filter
    "curves": "lighter",                         // ffmpeg preset name, or {"master": "0/0.05 1/0.95"}
    "colorbalance": {"rs": 0.05, "bs": -0.05},
    "sharpen": 0.6, "vignette": true, "grain": 6,
    "vf": "any extra ffmpeg filters"
  },
  "clips": [
    {
      "src": "footage/a.mp4", "in": 3.2, "out": 5.0,    // or "duration" instead of "out"
      "speed": 1.0,                                      // audio pitch-preserved via atempo
      "fit": "cover", "focus": [0.5, 0.35],             // crop center (x,y 0..1) when reframing
      "zoom": {"from": 1.0, "to": 1.1, "ease": "inout", "x": 0.5, "y": 0.4},  // in|out|inout|linear
      "grade": {"eq": {"saturation": 1.2}},             // merged over global; false = ungraded
      "transition": {"type": "fade", "duration": 0.25}, // between previous clip and this one
      "volume": 1.0, "mute": false,
      "audio_fade_in": 0.1, "audio_fade_out": 0.1,
      "fade_in": 0.2, "fade_out": 0.2,                  // picture fades inside the clip
      "vf": "hflip",                                    // per-clip extra filters
      "tonemap": true,                                  // HDR→SDR for HLG/PQ (auto-detected)
      "label": "hook line 1"
    },
    {"src": "references/photo.jpg", "duration": 1.5, "zoom": {"from": 1.0, "to": 1.06}}
  ],
  "overlays": [                                  // images, alpha video, HyperFrames/Remotion renders
    {"src": "work/job/title.webm", "start": 0.0, "end": 2.5, "position": "top",   // center|top|bottom|full
     "width": 0.8, "opacity": 1.0, "fade": 0.15},  // width ≤1 = fraction of frame width; x/y = ffmpeg exprs
    {"src": "assets/logos/logo.png", "start": 0, "end": 30, "x": "W-w-40", "y": "40", "width": 160}
  ],
  "captions": "work/job/captions.ass",           // or {"file": ..., "fontsdir": "assets/fonts"}
  "music": {"src": "assets/music/track.mp3", "start": 0, "offset": 12.5, "volume": 0.25,
            "duck": true, "duck_ratio": 8, "fade_in": 0.3, "fade_out": 1.5, "loop": true},
                                                 // or a list of music objects
  "sfx": [{"src": "assets/sfx/whoosh.wav", "at": 2.1, "volume": 0.6}],
  "fade_in": 0, "fade_out": 0.5,                 // whole-video fades
  "loudness": -14,                               // LUFS (null = skip); -14 social, -16 podcasts/YouTube-ish
  "encoder": "libx264",                          // or "nvenc" (RTX GPU) for faster finals
  "crf": 18, "preset": "medium"
}
```

Transition types (xfade): fade, fadeblack, fadewhite, dissolve, wipeleft/right/up/down,
slideleft/right/up/down, smoothleft/right/up/down, circleopen/close, circlecrop, rectcrop,
distance, radial, pixelize, zoomin, hblur, fadegrays, squeezeh/v, diagtl/br, hlslice,
hrslice, vuslice, vdslice, coverleft/right, revealleft/right. `cut` (default) = hard cut.

The timeline file (`<output>.timeline.json`) lists each clip's `out_start`/`out_end` in the
rendered video — use it to place overlays, SFX and captions by output time.
