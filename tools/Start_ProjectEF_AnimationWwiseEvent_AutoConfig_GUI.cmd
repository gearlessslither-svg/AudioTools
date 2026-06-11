@echo off
chcp 65001 >nul
setlocal
title ProjectEF Animation Wwise Event AutoConfig GUI

set "SCRIPT=%~dp0ProjectEF_AnimationWwiseEvent_AutoConfig_GUI.py"

if not exist "%SCRIPT%" (
  echo Missing Animation Wwise Event AutoConfig GUI:
  echo %SCRIPT%
  pause
  exit /b 1
)

set PYTHONDONTWRITEBYTECODE=1
python -B "%SCRIPT%"

if errorlevel 1 (
  echo.
  echo Animation Wwise Event AutoConfig GUI failed. See the error above.
  pause
  exit /b 1
)

endlocal
