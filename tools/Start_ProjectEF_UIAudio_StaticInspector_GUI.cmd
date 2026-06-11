@echo off
setlocal
title ProjectEF UI Audio Static Inspector

set "SCRIPT=%~dp0ProjectEF_UIAudio_StaticInspector_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing UI Audio Static Inspector GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo ProjectEF UI Audio Static Inspector failed. See the error above.
  pause
  exit /b 1
)

endlocal
