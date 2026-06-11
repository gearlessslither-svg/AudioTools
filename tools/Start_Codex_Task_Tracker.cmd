@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".codex-resume\scan-codex-tasks.ps1"
pause
