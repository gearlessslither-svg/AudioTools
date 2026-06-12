@echo off
chcp 65001 >nul
setlocal
title ProjectEF Audio Debug Assistant

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%projectef_audio_debug_assistant.py"

if not exist "%SCRIPT%" (
  echo Missing script:
  echo %SCRIPT%
  pause
  exit /b 1
)

echo ===============================================
echo ProjectEF Audio Debug Assistant
echo ===============================================
echo.
echo Example:
echo   Stamina
echo   Play_Stamina
echo   游戏联调里 Play_Stamina 为什么没有声音
echo.
set /p DESC=Scenario / Event / Wwise node: 
if "%DESC%"=="" exit /b 0

echo.
echo Debug mode:
echo   auto  - infer from description
echo   wwise - Wwise Authoring local debug
echo   game  - Unity/Wwise runtime log debug
echo   both  - run both paths
set /p MODE=Mode [auto]: 
if "%MODE%"=="" set "MODE=auto"

python -B "%SCRIPT%" "%DESC%" --debug-mode "%MODE%"
set "RC=%ERRORLEVEL%"
echo.
echo Exit code: %RC%
pause
exit /b %RC%
