@echo off
setlocal
title ProjectEF Audio Follow Launcher

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%Start_ProjectEF_UnityWwise_RuntimeAudioFollow.ps1"

if not exist "%PS_SCRIPT%" (
  echo Missing PowerShell launcher:
  echo %PS_SCRIPT%
  pause
  exit /b 1
)

start "ProjectEF Unity Wwise Runtime Audio Follow - Visible" powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%PS_SCRIPT%"

endlocal
