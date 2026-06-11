@echo off
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File ".codex-resume\test-codex-compact-link.ps1"
pause
