@echo off
chcp 65001 >nul
setlocal
title ProjectEF Tool Inventory HTML

set "SCRIPT=%~dp0ProjectEF_ToolInventory_HTML\ProjectEF_ToolInventory_HTML.py"

if not exist "%SCRIPT%" (
  echo Missing ProjectEF Tool Inventory HTML script:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo ProjectEF Tool Inventory HTML failed. See the error above.
  pause
  exit /b 1
)

endlocal
