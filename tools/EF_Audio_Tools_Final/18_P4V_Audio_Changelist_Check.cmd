@echo off
setlocal
title P4V Audio Changelist Check

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_P4V_AudioChangelist_Check.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
