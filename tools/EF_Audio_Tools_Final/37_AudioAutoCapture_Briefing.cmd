@echo off
setlocal
title Audio AutoCapture + Briefing

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioAutoCapture_Control.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
