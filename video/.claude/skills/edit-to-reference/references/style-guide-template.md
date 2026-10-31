# Style guide — <reference name(s)>

Source: <duration> @ <WxH> <fps>. Analyzed <date>. Evidence: work/ref_analysis/<stem>/

## PACING
- cuts/sec overall: X (by thirds: a / b / c) → target for our runtime: N cuts
- shot length median / min / max; where the long hold is and why
- builds/sec (pops within shots): Y → perceived events/sec X+Y
- what cuts land on: beats (cuts_on_onsets_ratio) / word starts / sentence ends

## CAPTIONS
- register system: each treatment (font class, weight, case, color, stroke/box, position,
  words-at-a-time, animation) AND the condition that selects it
- timing: word-synced karaoke / phrase chunks / leads or trails the voice
- make_captions.py settings that reproduce it: --font … --size … --color … --highlight … --words … --case … --pos … [--pop] [--box …]

## GRAPHIC LANGUAGE
- named device → looks like / FOR (function) / trigger condition / how we build it
  (PNG overlay, HyperFrames, Remotion, ffmpeg filter)
- the once-only trick: what, where in the reference, which of our beats gets it

## B-ROLL GRAMMAR
- what counts as B-roll, framing (full-bleed, blur-fill, floating card), dwell time,
  entry/exit, what kind of line triggers it

## COLOR & GRADE
- character (key, contrast, saturation, warmth, black lift, split tone) with the numbers
- per-mode differences (face vs B-roll vs graphics)
- our recipe: LUT from match_grade.py (strength) + eq/temperature/vignette/grain values

## SOUND DESIGN
- music: genre, BPM, energy arc, where it drops/ducks, ending (user-supplied track: which one, offset)
- SFX vocabulary: whoosh/impact/click/riser → what each lands on, level vs voice
- loudness target (reference measured X LUFS)

## TEMPLATE
- structure taken from template/: sections, bumpers, title/logo placement, safe margins

## BUILD DIRECTIVES
| # | our line / beat | out time | cuts within | visual (clip, framing, zoom) | caption register | builds | SFX |
|---|---|---|---|---|---|---|---|

Check before building: sum of cuts within ~15% of target; exactly one row carries the
once-only trick; every visual uses a named device (new ones flagged as departures).
