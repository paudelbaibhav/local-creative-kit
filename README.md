# local-creative-kit

Two Claude Code workspaces for making media on your own machine with free, local tools:

- **[`video/`](video)**: edit your footage to match a reference video. Claude measures the
  reference (cut rhythm, shot lengths, grade, captions, loudness), writes the style down as
  numbers, builds an edit list, renders it with ffmpeg, then measures the render against the
  reference and fixes the gaps.
- **[`music/`](music)**: write and produce full songs with [ACE-Step 1.5](https://github.com/ACE-Step/ACE-Step-1.5),
  and turn voice memos (humming, singing, beatboxing) into MIDI and notes Claude can read.

Open either folder in Claude Code and ask in plain words: "edit footage/ like references/reel.mp4",
"make a 3-minute lo-fi song from this hum". Each folder's `CLAUDE.md` tells Claude how to work there.

## video/

### Tools

| tool | does |
|---|---|
| `analyze_reference.py` | shots and cut times, cuts/sec by section, shot-length histogram, motion and look stats per shot, palette, contact sheets, spectrogram, LUFS, tempo and cut-on-beat ratio, transcript |
| `transcribe.py` | local Whisper word timings |
| `speech_edl.py` | talking-head rough cut: drops long pauses and isolated filler words |
| `match_grade.py` | bakes a `.cube` LUT that moves your clip's look toward the reference, plus a before/after preview |
| `beats.py` | BPM, beat grid and downbeats as cut points |
| `render_edl.py` | renders a JSON edit list: clips, speed, zoom, reframing (cover with focus point, blur bars), transitions, grade, music with ducking, SFX, overlays, captions, loudness. Segments are cached |
| `make_captions.py` | word-timed `.ass` captions (karaoke highlight, pop, box) mapped through the edit |
| `qa.py` | black or frozen frames, dead air, LUFS and true peak, duration, pacing and look against the reference |

The skill in `.claude/skills/edit-to-reference/` is the method Claude follows. The EDL format is
in its `references/edl-schema.md`, and `examples/edit.json` uses every renderer feature
(its media is not included; point it at your own files).

### Setup

You need Python 3.12, [ffmpeg](https://ffmpeg.org) on your PATH, and [uv](https://docs.astral.sh/uv/)
(or plain `venv` + `pip`).

```bash
cd video
uv venv --python 3.12
uv pip install -r requirements.txt
```

Optional extras the skill uses when present:

```bash
# short-form playbook, cut-mistakes rules and 406 HyperFrames motion cards (MIT, needs Node)
git clone https://github.com/nateherkai/herk-edit-kit tools/herk-edit-kit
(cd tools/herk-edit-kit && npm ci)
# long-form notes on cloning a reel's style (no license; read-only reference)
git clone https://github.com/krusemediallc/video-editor-agent tools/video-editor-agent
```

`.mcp.json` registers the [Kinocut](https://pypi.org/project/kinocut/) MCP server (typed editing
tools via `uvx`); Claude Code asks you to approve it the first time. Kdenlive is handy for
hand-tweaks but not required.

### Folders

| folder | contents |
|---|---|
| `references/` | videos and photos whose look and feel to match |
| `template/` | a structural template: a video, a project file, or a written spec |
| `footage/` | your raw clips |
| `assets/` | `music/`, `fonts/`, `sfx/`, `logos/` |
| `work/` | Claude's style guides, edit lists, transcripts, LUTs and caches |
| `output/` | finished videos |

Your media stays out of git (see `.gitignore`).

## music/

Windows only for now (`produce.py` starts and stops the ACE-Step server with Windows process calls).

### Setup

1. Install ACE-Step 1.5 into `music/ACE-Step-1.5` by following
   [its README](https://github.com/ACE-Step/ACE-Step-1.5), so that
   `ACE-Step-1.5/.venv/Scripts/acestep-api.exe` exists. It runs on a 6 GB GPU.
2. For the voice-memo tools (Python 3.10):

   ```powershell
   cd music\voice-tools
   uv venv --python 3.10
   uv pip install -r requirements.txt
   ```

### Use

```powershell
# a song from songs/<name>/lyrics.txt
ACE-Step-1.5\.venv\Scripts\python.exe produce.py songs\example --caption "dreamy indie pop, soft female vocal, warm synths, night drive" --duration 120 --bpm 92

# follow the sound of one of your tracks
... produce.py songs\example --caption "..." --duration 120 --ref my-songs\draft.mp3 --ref-strength 0.5

# rebuild a track with new lyrics (cover mode)
... produce.py songs\example --caption "..." --duration 120 --src my-songs\draft.mp3
```

Each run writes `<song>-v1.mp3`, `<song>-v2.mp3` and `settings.json` with the seeds, so a take
can be reproduced. The server restarts before each job and retries once if it crashes, because
long songs on small GPUs have segfaulted a reused server.

`voice-tools/listen.py <memo>` writes a transcript, the hummed melody as MIDI, and the key and
tempo. `voice-tools/beat.py <memo>` turns a beatboxed or tapped beat into a kick/snare/hat grid
and a drum MIDI file.

`start-music-server.bat` runs the ACE-Step API on its own; `start-music-studio-ui.bat` opens
ACE-Step's web UI if you'd rather make songs in the browser.

## License

MIT for everything in this repo. The optional third-party kits keep their own licenses.
