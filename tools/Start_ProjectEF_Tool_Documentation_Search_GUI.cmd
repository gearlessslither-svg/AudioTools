@echo off
chcp 65001 >nul
setlocal
title ProjectEF Tool Documentation Search GUI

set "SCRIPT=%~dp0ProjectEF_Tool_Documentation_Search_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing GUI script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo Tool documentation search GUI failed. See the error above.
  pause
  exit /b 1
)

endlocal
