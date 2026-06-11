@echo off
chcp 65001 >nul
setlocal
title ProjectEF Animation Wwise Event AutoConfig CLI

set "SCRIPT=%~dp0ProjectEF_AnimationWwiseEvent_AutoConfig.py"
set "UNITY_ROOT=D:\EF New\Client\TargetProject"
set "WWISE_ROOT=D:\EF Wwise\ProjectEF"

if not exist "%SCRIPT%" (
  echo Missing Animation Wwise Event AutoConfig script:
  echo %SCRIPT%
  pause
  exit /b 1
)

echo ProjectEF Animation Wwise Event AutoConfig CLI
echo.
set /p ANIMATION=Animation .anim/.fbx name or path: 
set /p WWISE_EVENT=Wwise Event name: 
set /p PREFAB=Prefab name/path (optional, Enter for auto): 
echo.

if "%PREFAB%"=="" (
  python -B "%SCRIPT%" --unity-root "%UNITY_ROOT%" --wwise-root "%WWISE_ROOT%" --animation "%ANIMATION%" --wwise-event "%WWISE_EVENT%" --apply
) else (
  python -B "%SCRIPT%" --unity-root "%UNITY_ROOT%" --wwise-root "%WWISE_ROOT%" --animation "%ANIMATION%" --wwise-event "%WWISE_EVENT%" --prefab "%PREFAB%" --apply
)

if errorlevel 1 (
  echo.
  echo Animation Wwise Event AutoConfig failed. See the error above.
  pause
  exit /b 1
)

pause
endlocal
