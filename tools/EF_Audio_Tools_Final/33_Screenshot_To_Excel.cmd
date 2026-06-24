@echo off
chcp 65001 >nul
setlocal
title Screenshot To Excel

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_Screenshot_To_Excel.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
