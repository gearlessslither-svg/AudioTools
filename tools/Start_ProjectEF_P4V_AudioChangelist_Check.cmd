@echo off
chcp 65001 >nul
setlocal
title ProjectEF P4V Audio Changelist Check

set "SCRIPT=%~dp0analyze_projectef_p4v_audio_changelist.py"

if not exist "%SCRIPT%" (
  echo Missing script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%" --open-report

if errorlevel 1 (
  echo.
  echo P4V audio changelist check failed. See the error above.
  pause
  exit /b 1
)

echo.
echo Done. The Markdown report was opened and also saved under the Wwise reports folder.
pause
endlocal
