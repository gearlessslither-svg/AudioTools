@echo off
chcp 65001 >nul
setlocal
title ProjectEF Audio Codex Task Card

set "SCRIPT=%~dp0ProjectEF_AudioCodexTaskCard_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing GUI script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo ProjectEF Audio Codex Task Card GUI failed. See the error above.
  pause
  exit /b 1
)

endlocal
