@echo off
chcp 65001 >nul
setlocal
title ProjectEF Tool Inventory HTML

set "LAUNCHER=G:\AI\Material\Wwise\Tools\Start_ProjectEF_ToolInventory_HTML.cmd"

if not exist "%LAUNCHER%" (
  echo Missing ProjectEF Tool Inventory launcher:
  echo %LAUNCHER%
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
