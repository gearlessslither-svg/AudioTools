@echo off
setlocal
title Wwise Audio Logic Tester

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_Wwise_AudioLogicTester_GUI.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
