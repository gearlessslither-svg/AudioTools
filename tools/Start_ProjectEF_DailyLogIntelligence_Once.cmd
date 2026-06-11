@echo off
setlocal
title ProjectEF Daily Audio Log Intelligence - Once

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_ProjectEF_DailyLogIntelligence_Once.ps1"
if errorlevel 1 (
  echo.
  echo Daily log intelligence failed. See the error above.
  pause
  exit /b 1
)

pause
endlocal
