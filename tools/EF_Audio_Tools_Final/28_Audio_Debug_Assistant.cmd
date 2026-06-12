@echo off
chcp 65001 >nul
setlocal
title ProjectEF Audio Debug Assistant

set "TOOL_DIR=G:\AI\Material\Wwise\Tools"
set "LAUNCHER=%TOOL_DIR%\Start_ProjectEF_Audio_Debug_Assistant.cmd"

if not exist "%LAUNCHER%" (
  echo Missing launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
