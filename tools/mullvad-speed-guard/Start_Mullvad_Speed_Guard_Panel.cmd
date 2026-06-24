@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" "http://127.0.0.1:18790/"
  python guard_panel_server.py --port 18790
) else (
  where py >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    start "" "http://127.0.0.1:18790/"
    py -3 guard_panel_server.py --port 18790
  ) else (
    echo Python was not found. Install Python 3 and try again.
    pause
    exit /b 1
  )
)
