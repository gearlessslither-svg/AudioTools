@echo off
setlocal
title ProjectEF Unity Wwise Audio Log Monitor GUI

set "SCRIPT_DIR=%~dp0"
set "PY_SCRIPT=%SCRIPT_DIR%ProjectEF_UnityWwise_AudioLogMonitor_GUI.py"
set PYTHONDONTWRITEBYTECODE=1

if not exist "%PY_SCRIPT%" (
  echo Missing GUI script:
  echo %PY_SCRIPT%
  pause
  exit /b 1
)

python -B "%PY_SCRIPT%"
if errorlevel 1 (
  echo.
  echo GUI failed to start. See the error above.
  pause
  exit /b 1
)

endlocal
