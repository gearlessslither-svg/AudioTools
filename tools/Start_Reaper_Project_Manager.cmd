@echo off
chcp 65001 >nul
setlocal
title REAPER Project Manager

set "SCRIPT=%~dp0Reaper_Project_Manager_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing REAPER project manager:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo REAPER project manager failed. See the error above.
  pause
  exit /b 1
)

endlocal
