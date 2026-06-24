@echo off
setlocal
title ProjectEF Audio Identity Overlay Map Export

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioIdentityOverlay_MapExport.cmd"

if not exist "%LAUNCHER%" (
  echo Missing source launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"
endlocal
