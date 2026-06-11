@echo off
setlocal
set ROOT=%~dp0..
powershell -ExecutionPolicy Bypass -File "%ROOT%\.codex-resume\resume-ollama-sound-finder.ps1" %*
pause
