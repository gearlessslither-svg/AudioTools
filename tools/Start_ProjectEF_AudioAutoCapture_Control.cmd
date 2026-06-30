@echo off
setlocal
title ProjectEF Audio AutoCapture + Briefing
set "TOOLS=%~dp0"
set "SCRIPT=%TOOLS%projectef_audio_autocapture_gui.py"
set "PYTHONDONTWRITEBYTECODE=1"

if not exist "%SCRIPT%" (
  echo Missing GUI: %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Audio AutoCapture GUI failed. See the error above.
  pause
  exit /b 1
)
endlocal
