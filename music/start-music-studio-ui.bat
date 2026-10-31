@echo off
REM Opens ACE-Step's own web interface at http://127.0.0.1:7860
REM Use this to make songs yourself in the browser, without Claude.
cd /d "%~dp0ACE-Step-1.5"
set PYTHONUNBUFFERED=1
echo Starting ACE-Step studio UI. Open http://127.0.0.1:7860 in your browser.
".venv\Scripts\acestep.exe"
pause
