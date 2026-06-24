@echo off
chcp 65001 >nul
setlocal
title Audio Codex Task Card

set "SOURCE=G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioCodexTaskCard_GUI.cmd"

if not exist "%SOURCE%" (
  echo Missing source launcher:
  echo %SOURCE%
  pause
  exit /b 1
)

call "%SOURCE%"
endlocal
