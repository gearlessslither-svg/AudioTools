@echo off
setlocal
title AudioTools Git Sync

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioTools_GitSync_GUI.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
