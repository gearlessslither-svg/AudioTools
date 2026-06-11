@echo off
setlocal
title P4V Changelist Organizer GUI

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_P4V_Changelist_Organizer_GUI.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
