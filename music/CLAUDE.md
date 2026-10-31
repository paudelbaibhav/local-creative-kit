# Music workspace

Write and produce songs with the local ACE-Step 1.5 server (`ACE-Step-1.5/`, port 8001).

- One folder per song: `songs/<name>/lyrics.txt`. Section tags in square brackets
  (`[Verse 1]`, `[Chorus]`, `[Bridge]`, `[Outro]`, `[Instrumental]`); a short performance note
  after a dash is allowed (`[Chorus - stacked harmonies]`). See `songs/example/`.
- Generate: `ACE-Step-1.5/.venv/Scripts/python.exe produce.py songs/<name> --caption "<genre, instruments, vocal, mood>" --duration <s> [--bpm N] [--key "A minor"] [--timesig "6/8"] [--language en] [--seed N]`.
  Writes `<name>-v1.mp3`, `-v2.mp3` and `settings.json` (keep it: the seeds reproduce a take).
- Style reference: `--ref my-songs/<track> [--ref-strength 0-1]` keeps a track's sound.
- Cover mode: `--src <track> [--src-strength 1.0]` rebuilds a track's structure and melody
  with new lyrics; lyrics `[Instrumental]` re-creates it without vocals.
- `--tag <x>` keeps variants apart (`<name>-<x>-v1.mp3`).
- The server is restarted before each job (a fresh one is faster and reused ones have crashed
  on long songs); `--keep-server` skips that.
- User recordings: `voice-memos/` (hums, sung ideas, beatboxing). Read them with
  `voice-tools/.venv/Scripts/python.exe voice-tools/listen.py <file>` (transcript, melody MIDI,
  key and tempo) and `voice-tools/beat.py <file> [--bpm N] [--start S]` (drum grid + MIDI).
  Output lands in `voice-tools/out/<memo>/`; read `summary.txt` / `beat.txt`.
- `my-songs/` holds the user's own tracks; never overwrite them.
