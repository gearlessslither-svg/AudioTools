@echo off
setlocal
title ProjectEF Wwise Audio Logic Tester

set "SCRIPT=%~dp0ProjectEF_Wwise_AudioLogicTester_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Audio Logic Tester GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo ProjectEF Wwise Audio Logic Tester failed. See the error above.
  pause
  exit /b 1
)

endlocal
