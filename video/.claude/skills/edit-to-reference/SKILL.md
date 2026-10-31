---
name: edit-to-reference
description: >-
  Edit the user's footage so it matches reference videos/photos and a reference template —
  pacing, cut rhythm, color grade, captions, graphics, transitions, music and sound. Use
  whenever the user drops assets into references/, template/ or footage/ and says "edit this
  like the reference", "match this style", "make it look like this", "use this template",
  "cut this video", "make a reel/short/vlog from my clips", or asks to re-edit, recolor,
  re-caption or re-pace a video. Free/local stack: ffmpeg, faster-whisper, PySceneDetect,
  OpenCV, Kdenlive, plus the hyperframes / remotion skills for motion graphics.
---

# edit-to-reference

An editing style is a countable system, not a vibe: a cut density, a shot-length rhythm, a
caption grammar, a small vocabulary of graphics, a grade, a mix. Measure the reference,
write that system down, build the edit to the numbers, then measure the render against the
reference until they agree. Method adapted from [krusemediallc/video-editor-agent](https://github.com/krusemediallc/video-editor-agent)
(if you cloned it into `tools/video-editor-agent/`, `.claude/skills/reel-style-clone/references/method.md` has the
long-form forensic heuristics — read §5–§8 there when a reference is graphics-heavy).

All commands run from the project root (this `video/` folder) with the project venv's python
(`.venv/Scripts/python` on Windows, `.venv/bin/python` elsewhere).

## Folder contract

| folder | who writes | contents |
|---|---|---|
| `references/` | user | reference videos and photos (the look/feel to match) — never modify |
| `template/` | user | the structural template: a video, a project file, a written spec, a frame layout |
| `footage/` | user | raw clips to edit — never modify |
| `assets/music`, `assets/fonts`, `assets/sfx`, `assets/logos` | user/me | music beds, .ttf/.otf, hits, brand marks |
| `work/<job>/` | me | style guide, EDL, captions, logs |
| `work/ref_analysis/`, `work/transcripts/`, `work/luts/`, `work/segments/`, `work/qa/` | tools | evidence and caches |
| `output/` | me | deliverables only |

## Toolkit (`tools/`)

| tool | does |
|---|---|
| **Kinocut MCP** (`kinocut` in `.mcp.json`) | 20 core typed editing tools (trim, merge, subtitles, color, shorts repurposing, quality checks); `KINOCUT_TOOLS=all` for 205. Use when a typed tool beats writing an EDL |
| `analyze_reference.py <file/dir>` | shots + cut times, cuts/sec (overall and by thirds), shot-length histogram, per-shot motion + look stats, palette, contact sheets, spectrogram/waveform, LUFS, tempo + cut-on-beat ratio, transcript → `work/ref_analysis/<stem>/summary.md` |
| `transcribe.py <file/dir>` | local whisper word timings → `work/transcripts/<stem>.json/.txt` |
| `speech_edl.py <clip>` | talking-head rough cut: drops pauses > max-gap and filler words → EDL clip list with text |
| `match_grade.py --ref X --src Y` | bakes a `.cube` LUT moving Y's look toward X (Lab mean/std transfer, strength-blended) + before/after/ref preview image |
| `beats.py <music>` | BPM + beat grid + downbeats → cut points |
| `render_edl.py <edl.json> [--preview\|--plan]` | renders the EDL (schema: [references/edl-schema.md](references/edl-schema.md)); writes `<output>.timeline.json` |
| `make_captions.py --timeline …` | word-timed styled .ass captions (karaoke highlight, pop, box, case) mapped through the edit |
| `qa.py <render> --ref <metrics.json>` | black/frozen frames, dead air, LUFS/true peak, duration vs plan, pacing + look deltas vs reference, contact sheets |

GUI: Kdenlive (optional) for hand-tweaks. Motion graphics (kinetic titles, lower thirds,
animated stickers, charts): build with the **hyperframes** or **remotion** skills, render
with alpha (`.webm` VP9 or `.mov` ProRes 4444), place as `overlays` in the EDL.

## herk-edit-kit (`tools/herk-edit-kit/`, optional, MIT — AIS brand assets inside are NOT reusable)

[nateherkai/herk-edit-kit](https://github.com/nateherkai/herk-edit-kit), a field-tested
talking-head/short-form kit. If `tools/herk-edit-kit/` is missing, skip this section (setup is in
the README). Run its scripts with `node` from the project root using paths into `tools/herk-edit-kit/`.

Motion card → overlay (verified): pick a card from `style-library/registry.json`, fill its
`data-slot` text in a copy under `work/<job>/cards/` (keep the relative `tokens.css`/gsap
paths working, or copy them alongside), then
`cd tools/herk-edit-kit && npx hyperframes render style-library/<NN-style> -c cards/<tier>/<card>.html --format webm -q high -o <abs path>/work/<job>/cards/<name>.webm`
(transparent VP9, 1920x1080, ~45 s per 7 s card) and add it to the EDL `overlays`
(`"fit": "full"` for 16:9 edits; scale/position for vertical). Cards are 16:9 — for 9:16
reels build/adapt a card at 1080x1920 instead of shrinking one.

Kit scripts that work on our local-Whisper transcripts:
`node tools/herk-edit-kit/.claude/skills/cut-silences/scripts/cut-silences.mjs work/transcripts/<stem>.json --video <src> --out-dir work/<job> [--apply --output ...]`
and `.../cut-mistakes/scripts/find-cut-candidates.mjs` → review → `apply-cuts.mjs`.

| need | read |
|---|---|
| house rules for reels/Shorts: pacing numbers, layouts, story arc, B-roll order, captions, SFX, loudness, QA | `docs/EDITING-PLAYBOOK.md` (also `docs/SHORT-FORM.md`) |
| retakes / stutters / false starts — judgment rules for what is NOT a mistake | `.claude/skills/cut-mistakes/SKILL.md` |
| narrative arc, visual callbacks, beat sheets | `.claude/skills/video-storytelling/SKILL.md` |
| motion vocabulary, transitions | `MOTION_PHILOSOPHY.md` |
| 406 ready motion-graphics cards (HyperFrames, tier1 takeovers / tier2 overlays, named text slots) | `style-library/GUIDE.md`, `style-library/registry.json` |
| whole-scene templates (dark graph paper, glass popout) | `style-templates/` |

Our transcripts (`work/transcripts/*.json`) already carry its common format
(`words[].text/start/end`, `audio_duration_secs`), so its cutters can read them directly.

**Priority:** the user's reference and template win. Where they are silent (e.g. no
reference for captions or SFX), fall back to the playbook's house rules. Rules adopted
into our tools: frame-exact cuts (no A/V drift), fillers dropped only when isolated by
silence, captions 2 frames early, never speed up the voice, music ~11 dB under voice,
-14 LUFS / ≤ -1.5 dBTP measured on the delivered file, never fade the last spoken word.

## Workflow

### 1. Intake
List `references/`, `template/`, `footage/`, `assets/`. Probe every file
(`ffprobe` or `vtk.probe`). If any of these is unknowable from the files, ask once, briefly:
target platform/aspect, target length, which footage is A-roll vs B-roll, music to use
(only use music the user supplied or explicitly approved). Otherwise proceed.

### 2. Measure the references
`python tools/analyze_reference.py references/` then, for each reference:
read `summary.md`, **look at every contact sheet**, then the outlier shot frames, the
spectrogram/waveform. For photos, view the photo itself: the numbers only cover tone.
Several references of one style → merge them; conflicting references → ask which wins.

### 3. Write the style guide — `work/<job>/style-guide.md`
Use [references/style-guide-template.md](references/style-guide-template.md). The sections
are a contract. The non-obvious parts that make a clone read right:
- **Conditions, not looks.** If captions/graphics change treatment, find the condition that
  predicts it (face on screen? section? emphasis word?) and record the rule.
- **Builds/sec, not just cuts/sec.** Count elements that pop on within a shot (word groups,
  zoom punches, stickers). Perceived pace ≈ cuts + builds.
- **The once-only trick.** One signature moment (flash, speed ramp, freeze, invert): use it
  exactly once at the equivalent narrative beat.
- **Function over appearance.** Every device gets what it is FOR (proof, emphasis, reset,
  humor), so it can be deployed on lines the reference never had.
- **Pacing by section.** Hooks usually cut ~2× faster than the body; keep deliberate long holds.

### 4. Read the template
- Video template → measure it like a reference *for structure*: section order and lengths,
  intro/outro bumpers, where titles/logo sit, safe margins. Reuse its bumpers as clips or overlays.
- Project file (.kdenlive/.mlt/.xml/.prproj/.drp/CapCut draft) → read its structure
  (tracks, durations, effects) and mirror it in the EDL; say if some feature can't be mirrored.
- Image/PDF/text spec → follow it literally (positions, fonts, colors, durations).
Record template decisions in the style guide under BUILD DIRECTIVES.

### 5. Log the footage
`python tools/transcribe.py footage/`, then a contact sheet per clip
(`ffmpeg -i clip -vf "fps=1,scale=320:-2,tile=6x4" sheet.png`) and **look at it**. Write
`work/<job>/footage-log.md`: per clip — content, usable ranges, best moments, faces/subject
position (for `focus` when reframing), shake/exposure problems.

### 6. Grade
Per camera/lighting group: `match_grade.py --ref references/<ref> --src footage/<clip> --name <job>_<group>`.
Open the preview image. Too strong/skin looks off → `--strength 0.5–0.7`. Then fine-tune
with `eq`/`temperature`/`vignette`/`grain` in the EDL `grade`. Grade numbers in the guide
(warmth, black_pt lift, saturation) are the targets.

### 7. Build the EDL — `work/<job>/edit.json`
- Total cuts ≈ ref cuts/sec × target runtime, distributed per section like the reference.
- Talking head: start from `speech_edl.py` output; reorder/delete by `text`.
- Music-driven: `beats.py` and put cut points on beats (or downbeats, if the reference does —
  check its `cuts_on_onsets_ratio`).
- Only transitions the reference uses. Hard cuts are the default.
- Reframe 16:9 → 9:16 with `fit: cover` + `focus` on the subject; `fit: blur` for wide shots
  that must stay whole.
- Zoom punches/drifts via `zoom`; still frames must move (QA flags frozen pictures).
- Graphics → overlays; captions → step 8.
`render_edl.py --plan` to check the timeline numbers before rendering anything.

### 8. Captions
`make_captions.py --timeline output/<name>.timeline.json` with the style from the guide
(font file in `assets/fonts/`, size, colors, words-at-a-time, case, position, highlight,
pop). Keep text out of the platform UI zones on vertical video (top ~14%, bottom ~26%) and
off faces. Set `"captions"` in the EDL.

### 9. Render → look → QA → fix
1. `render_edl.py edit.json --preview` and view frames at every cut, caption and overlay
   (contact sheet + a few full frames). Fix obvious problems first.
2. Full render, then `qa.py output/<name>.mp4 --ref work/ref_analysis/<ref>/metrics.json`.
3. Read the report AND the render's contact sheets beside the reference's. Fix, re-render
   (segments are cached — only changed clips re-encode). **Max 3 rounds**, then show the
   user what's left and ask.
Auto-fix freely: cut nudges ≤ 0.5s, caption retiming, gain ≤ 3 dB, grade tweaks. Anything
that changes the story or drops content goes to the user.

### 10. Deliver
`output/<name>.mp4` plus a short note: what was matched (numbers vs reference), deliberate
departures, anything that needs the user's call. Keep `work/<job>/` for revision rounds.

## Gotchas
- Render at the reference's fps (24 vs 30 changes the feel).
- Phone HDR (HLG/PQ) is tone-mapped automatically per clip; check skin in the preview.
- Filter file paths (LUTs, .ass, fonts) are made project-relative by the tools; keep assets inside the project folder.
- Whisper on CPU (CUDA libs absent): `small` is the speed/accuracy sweet spot; `medium` for non-English or noisy audio.
- Scene detection can't see jump cuts within one angle; QA uses the timeline for pacing when that happens.
- Cut between phrases at real silence, never inside a phrase; fewer clean cuts beat many clipped ones.
- Captions: never white on a light background, never over mouth/chin (check the first 2.5 s frame by frame).
- Every shot moves: stills and screenshots get a `zoom` drift; QA flags frozen pictures.
- When the user gives a note, fix it AND add it to this skill as a rule so it never recurs.
- Beat-synced edits: pick the fps where one beat is a whole number of frames (96 BPM → 0.625 s =
  15 frames at 24 fps, 18.75 at 30) — otherwise frame snapping walks the cuts off the beat.
- A 16:9 two-person clip can't be cover-cropped to 9:16 without losing a face: use `fit: blur`
  and put text in the band above/below the picture. Place every label per shot against the
  faces actually in it (left/right/top), not one fixed position.
- Advanced transitions: prep graded 9:16 clips
  with ffmpeg (`-g 12` keyframes or HyperFrames freezes on seeks), then compose in HyperFrames.
  Whip = small slide (±130 px) + scale 1.26 overhang + SVG directional blur (never slide far:
  it uncovers black). Every revealed element needs a `tl.set(fromState, windowStart)` or it
  shows before it animates. Handwriting wipes (clip-path) need horizontal padding — script
  glyphs overhang their box. The registry's shader-transition blocks are static-DOM demos, not
  footage tools.
- Stills from `render --format png-sequence` are transparent and drop the root's background:
  paint the background on a full-bleed child and flatten onto a solid colour before delivery.
- Cut-out sticker collages (the photo-dump trend): `npx hyperframes remove-background in.jpg -o out.png`
  (local model, CPU ok, ~5 s/photo), then dilate the alpha into a white outline and crop. Big condensed type behind the hero cutout, stickers layered
  around, handwritten notes + doodles; keep a low-res cutout near native size.
- Grain makes CRF-18 files huge (~100 MB for 40 s): also deliver a ~9 Mbps `_share` encode.
- No music supplied → CC BY tracks: Kevin MacLeod mp3s download directly from
  `incompetech.com/music/royalty-free/mp3-royaltyfree/<Title>.mp3`; BudgetPixel pages expose
  `cdn.budgetpixel.com/audio-library/music/*.mp3`. Save a CREDIT.txt next to the track and tell the user to credit it.
