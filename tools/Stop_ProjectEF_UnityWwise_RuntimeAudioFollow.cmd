@echo off
setlocal
title Stop ProjectEF Unity Wwise Runtime Audio Follow

echo Stopping ProjectEF Unity/Wwise runtime audio follow processes...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'unity_wwise_runtime_log_audit.py|Start_ProjectEF_UnityWwise_RuntimeAudioFollow' -and $_.ProcessId -ne $PID }; foreach ($p in $procs) { Write-Host ('Stopping PID ' + $p.ProcessId + ' ' + $p.Name); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }; if (-not $procs) { Write-Host 'No listener process found.' }"

echo.
pause
endlocal
