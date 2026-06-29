@echo off
chcp 65001 >nul
setlocal
title REAPER Project Manager

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_Reaper_Project_Manager.cmd"

if not exist "%LAUNCHER%" (
  echo Missing REAPER project manager launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
