@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0\.."
if "%EF_WWISE_PROFILER_DURATION%"=="" set "EF_WWISE_PROFILER_DURATION=300"
if "%EF_WWISE_PROFILER_INTERVAL%"=="" set "EF_WWISE_PROFILER_INTERVAL=1"
python -B Tools\capture_projectef_wwise_profiler_voices.py --enable-profiler-data --start-capture --stop-capture-at-end --duration %EF_WWISE_PROFILER_DURATION% --interval %EF_WWISE_PROFILER_INTERVAL% --system-metrics
pause
