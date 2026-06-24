@echo off
chcp 65001 >nul
setlocal
title Daily Work Notes

set "SCRIPT=%~dp0EF_Work_Notes.py"

if not exist "%SCRIPT%" (
  echo Missing tool script:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo Daily Work Notes failed. See the error above.
  pause
  exit /b 1
)

endlocal
