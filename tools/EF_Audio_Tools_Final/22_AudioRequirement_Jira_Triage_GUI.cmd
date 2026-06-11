@echo off
setlocal
title Audio Requirement Jira Triage GUI

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioRequirementJiraTriage_GUI.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
