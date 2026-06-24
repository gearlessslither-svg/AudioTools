@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python traffic_float_widget.py
) else (
  where py >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    py -3 traffic_float_widget.py
  ) else (
    echo Python was not found. Install Python 3 and try again.
    pause
    exit /b 1
  )
)
