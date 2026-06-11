@echo off
setlocal
title ProjectEF Unity Wwise Runtime Audio Follow

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%Start_ProjectEF_UnityWwise_RuntimeAudioFollow.ps1"

if not exist "%PS_SCRIPT%" (
  echo Missing PowerShell launcher:
  echo %PS_SCRIPT%
  pause
  exit /b 1
)

echo Starting ProjectEF Unity/Wwise runtime audio follow...
echo.
echo Keep this window open while testing in Unity.
echo Press Ctrl+C or close this window to stop.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%PS_SCRIPT%"

endlocal
