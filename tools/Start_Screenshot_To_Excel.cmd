@echo off
chcp 65001 >nul
setlocal
title Screenshot To Excel

set "SCRIPT=%~dp0screenshot_to_excel.py"

if not exist "%SCRIPT%" (
  echo Missing Screenshot To Excel tool:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Screenshot To Excel failed. See the error above.
  pause
)
endlocal
