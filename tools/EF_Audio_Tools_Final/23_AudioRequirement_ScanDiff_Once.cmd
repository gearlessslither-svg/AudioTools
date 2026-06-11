@echo off
setlocal
chcp 65001 >nul
title Audio Requirement Scan Diff Once

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioRequirementJiraTriage_ScanDiff_Once.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
