@echo off
setlocal
title ProjectEF Audio Resource Jira Linker GUI

set "SCRIPT=%~dp0ProjectEF_AudioResourceJiraLinker_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Audio Resource Jira Linker GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

python "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Audio Resource Jira Linker GUI failed. See the error above.
  pause
)
endlocal
