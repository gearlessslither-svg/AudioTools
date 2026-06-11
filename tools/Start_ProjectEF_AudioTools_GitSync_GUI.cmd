@echo off
setlocal
title AudioTools Git Sync GUI

set "SCRIPT=G:\AI\Material\AudioTools_Repo\sync_gui.py"

if not exist "%SCRIPT%" (
  echo Missing AudioTools sync GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo AudioTools Git Sync failed. See the error above.
  pause
  exit /b 1
)

endlocal
