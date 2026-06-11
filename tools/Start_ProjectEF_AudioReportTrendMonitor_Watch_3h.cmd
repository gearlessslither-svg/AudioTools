@echo off
chcp 65001 >nul
setlocal
title ProjectEF Audio Report Trend Monitor - Watch 3h

set "SCRIPT=%USERPROFILE%\.codex\skills\audio-report-trend-monitor\scripts\audio_report_trend_monitor.py"
set "ROOT=G:\AI\Material\Wwise"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[IO.Path]::Combine($env:ROOT, [string]([char]0x62A5)+[string]([char]0x544A))"`) do set "REPORT_ROOT=%%D"

python "%SCRIPT%" ^
  --report-root "%REPORT_ROOT%" ^
  --latest 12 ^
  --max-file-mb 200 ^
  --out "%REPORT_ROOT%\ProjectEF_AudioReport_TrendSummary.md" ^
  --json-out "%REPORT_ROOT%\ProjectEF_AudioReport_TrendSummary.json" ^
  --watch ^
  --interval-hours 3

pause
endlocal
