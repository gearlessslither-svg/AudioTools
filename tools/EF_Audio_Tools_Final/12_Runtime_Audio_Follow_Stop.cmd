@echo off
chcp 65001 >nul
setlocal
title Stop ProjectEF Runtime Audio Follow

for %%I in ("%~dp0..") do set "TOOL_DIR=%%~fI"
set "LAUNCHER=%TOOL_DIR%\Stop_ProjectEF_UnityWwise_RuntimeAudioFollow.cmd"

if not exist "%LAUNCHER%" (
  echo Missing launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

pushd "%TOOL_DIR%"
call "%LAUNCHER%"
popd

endlocal
