@echo off
setlocal
title ProjectEF P4V Changelist Organizer GUI

set "SCRIPT=%~dp0ProjectEF_P4V_Changelist_Organizer_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing GUI script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo P4V changelist organizer GUI failed. See the error above.
  pause
  exit /b 1
)

endlocal
