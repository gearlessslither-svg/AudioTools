@echo off
chcp 65001 >nul
setlocal
title AI Work Impact Summary - Month

for %%I in ("%~dp0..") do set "TOOL_DIR=%%~fI"
set "LAUNCHER=%TOOL_DIR%\Start_AI_Work_Impact_Summary_Month.cmd"

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
