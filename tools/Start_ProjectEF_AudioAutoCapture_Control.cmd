@echo off
chcp 65001 >nul
setlocal
title ProjectEF Audio AutoCapture + Briefing
set "TOOLS=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%TOOLS%"

:menu
echo.
echo ============================================================
echo   ProjectEF 音频自动捕获 + 简报
echo ============================================================
echo   1. 现在启动自动捕获守护(前台,关窗即停)
echo   2. 生成每日简报(现在)
echo   3. 生成每周简报(现在)
echo   4. 注册:开机自启守护 + 每日/每周简报计划任务
echo   5. 取消注册(移除计划任务)
echo   6. 打开捕获目录 / 报告目录
echo   0. 退出
echo ------------------------------------------------------------
set /p "c=选择: "
if "%c%"=="1" ( python -B "%TOOLS%projectef_audio_autocapture_daemon.py" & goto menu )
if "%c%"=="2" ( python -B "%TOOLS%projectef_audio_briefing.py" --period daily & pause & goto menu )
if "%c%"=="3" ( python -B "%TOOLS%projectef_audio_briefing.py" --period weekly & pause & goto menu )
if "%c%"=="4" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS%Register_ProjectEF_AudioAutoCapture_Tasks.ps1" & pause & goto menu )
if "%c%"=="5" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOLS%Unregister_ProjectEF_AudioAutoCapture_Tasks.ps1" & pause & goto menu )
if "%c%"=="6" ( start "" "G:\AI\Material\Wwise\audio_debug_captures" & start "" "G:\AI\Material\Wwise\报告" & goto menu )
if "%c%"=="0" ( goto end )
goto menu

:end
endlocal
