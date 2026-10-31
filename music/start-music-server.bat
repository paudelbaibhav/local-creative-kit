@echo off
REM Starts the ACE-Step music API on http://127.0.0.1:8001
REM Runs the venv's launcher directly: "uv run" would re-check the lockfile
REM and try to fetch a 250MB flash-attn wheel from GitHub that isn't needed.
cd /d "%~dp0ACE-Step-1.5"
set PYTHONUNBUFFERED=1
echo Starting ACE-Step music server on http://127.0.0.1:8001 ...
echo Leave this window open while making music. Close it to stop the server.
".venv\Scripts\acestep-api.exe"
pause
