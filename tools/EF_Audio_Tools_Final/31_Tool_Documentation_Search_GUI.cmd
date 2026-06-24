@echo off
chcp 65001 >nul
setlocal
title Tool Documentation Search GUI

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_Tool_Documentation_Search_GUI.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
