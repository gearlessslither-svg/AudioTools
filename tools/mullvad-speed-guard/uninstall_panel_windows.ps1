$ErrorActionPreference = "SilentlyContinue"

$TaskName = "MullvadSpeedGuardPanel"
schtasks /End /TN $TaskName | Out-Null
schtasks /Delete /TN $TaskName /F | Out-Null

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*guard_panel_server.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Panel task removed: $TaskName"
