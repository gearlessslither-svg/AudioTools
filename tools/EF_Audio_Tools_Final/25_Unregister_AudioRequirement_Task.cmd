@echo off
setlocal
chcp 65001 >nul
title Unregister Audio Requirement Scheduled Task

set "SCRIPT=G:\AI\Material\Wwise\Tools\Unregister_ProjectEF_AudioRequirementJiraTriage_Task.ps1"

if not exist "%SCRIPT%" (
  echo Missing scheduled-task script:
  echo %SCRIPT%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Unregister scheduled task failed. See the error above.
  pause
)
endlocal
