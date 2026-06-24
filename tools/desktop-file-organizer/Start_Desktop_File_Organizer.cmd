@echo off
setlocal
cd /d "%~dp0"
python desktop_file_organizer.py
if errorlevel 1 (
  echo.
  echo Desktop File Organizer exited with an error.
  pause
)
