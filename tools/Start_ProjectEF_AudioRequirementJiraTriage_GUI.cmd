@echo off
setlocal
title ProjectEF Audio Requirement Jira Triage GUI

set "SCRIPT=%~dp0ProjectEF_AudioRequirementJiraTriage_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Audio Requirement Jira Triage GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

python "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Audio Requirement Jira Triage GUI failed. See the error above.
  pause
)
endlocal
