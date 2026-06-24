@echo off
setlocal
title ProjectEF Audio Jira Creator

set "SCRIPT=%~dp0ProjectEF_AudioJira_Creator_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Audio Jira Creator GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo ProjectEF Audio Jira Creator failed. See the error above.
  pause
  exit /b 1
)

endlocal
