@echo off
chcp 65001 >nul
setlocal
title Unregister ProjectEF Daily Log Scheduled Task

for %%I in ("%~dp0..") do set "TOOL_DIR=%%~fI"
set "PS_SCRIPT=%TOOL_DIR%\Unregister_ProjectEF_DailyLogIntelligence_Task.ps1"

if not exist "%PS_SCRIPT%" (
  echo Missing script:
  echo %PS_SCRIPT%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
pause

endlocal
