@echo off
chcp 65001 >nul
setlocal
title Sound Finder for Reaper

set "TOOL_DIR=C:\Users\user1\Documents\Reaper"
set "LAUNCHER=%TOOL_DIR%\Start_Sound_Finder.cmd"

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

