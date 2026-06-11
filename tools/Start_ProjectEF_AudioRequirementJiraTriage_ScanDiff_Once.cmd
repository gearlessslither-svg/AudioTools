@echo off
setlocal
chcp 65001 >nul
title ProjectEF Audio Requirement Scan Diff Once

set "SCRIPT=%~dp0ProjectEF_AudioRequirementJiraTriage_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Audio Requirement Jira Triage script:
  echo %SCRIPT%
  pause
  exit /b 1
)

python "%SCRIPT%" --scan-diff-once
if errorlevel 1 (
  echo.
  echo Audio requirement scan/diff failed. See the error above.
  pause
)
endlocal
