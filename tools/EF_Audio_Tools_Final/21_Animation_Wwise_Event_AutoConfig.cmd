@echo off
setlocal
title ProjectEF Animation Wwise Event AutoConfig GUI

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AnimationWwiseEvent_AutoConfig_GUI.cmd"

if not exist "%LAUNCHER%" (
  echo Missing Animation Wwise Event AutoConfig GUI launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"
endlocal
