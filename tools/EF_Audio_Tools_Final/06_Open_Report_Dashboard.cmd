@echo off
chcp 65001 >nul
setlocal
title Open ProjectEF Audio Report Dashboard

set "DASHBOARD=G:\AI\Material\Wwise\ProjectEF_reports_html\index.html"

if not exist "%DASHBOARD%" (
  echo Missing dashboard:
  echo %DASHBOARD%
  pause
  exit /b 1
)

start "" "%DASHBOARD%"

endlocal

