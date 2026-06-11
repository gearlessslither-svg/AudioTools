@echo off
setlocal
title ProjectEF UI Audio Static Inspector

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_UIAudio_StaticInspector_GUI.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
