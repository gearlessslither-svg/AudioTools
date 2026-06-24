@echo off
setlocal
title Audio Jira Creator

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioJira_Creator_GUI.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
