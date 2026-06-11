@echo off
setlocal
title EF Audio Tools GUI

set "SCRIPT=%~dp0EF_Audio_Tools_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing GUI script:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo EF Audio Tools GUI failed. See the error above.
  pause
  exit /b 1
)

endlocal
