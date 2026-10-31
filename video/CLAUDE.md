# Video editing workspace

Edit the user's footage to match their references and template. Use the
`edit-to-reference` skill (`.claude/skills/edit-to-reference/`) for any editing request.

- Python tools in `tools/`, run with the project venv's python (`.venv/Scripts/python` on
  Windows, `.venv/bin/python` elsewhere) from this folder: `python tools/<tool>.py`.
- User inputs: `references/`, `template/`, `footage/`, `assets/` — read-only for me.
- My work: `work/<job>/`; deliverables: `output/`.
- Free/local only unless the user opts in: ffmpeg, faster-whisper (CPU), PySceneDetect,
  OpenCV, auto-editor, Kdenlive (GUI), hyperframes/remotion skills.
- Optional third-party kits, cloned by the user (see README), not part of this repo:
  `tools/herk-edit-kit/` (MIT; its AIS brand assets are not reusable) and
  `tools/video-editor-agent/` (reference material only; no license, not vetted).
- `examples/edit.json` is an EDL that exercises every renderer feature; its media is not included.
- Kinocut MCP is registered in `.mcp.json` (project scope; approve it when Claude Code asks).
