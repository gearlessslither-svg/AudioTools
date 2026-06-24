$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $env:LOCALAPPDATA "MullvadSpeedGuard"
$Results = Join-Path $Runtime "results"
$Launcher = Join-Path $Runtime "run_auto_guard.cmd"
$Log = Join-Path $Results "auto_guard_supervisor.log"
$TaskName = "MullvadSpeedGuardAutoGuard"

New-Item -ItemType Directory -Force -Path $Results | Out-Null

$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = if ($python) {
  '"' + $python.Source + '"'
} else {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if (-not $py) { throw "Python 3 was not found. Install Python 3 and try again." }
  '"' + $py.Source + '" -3'
}

$script = Join-Path $Root "mullvad_speed_guard.py"
$lines = @(
  "@echo off",
  "cd /d `"$Root`"",
  "$prefix `"$script`" inventory auto-guard --interval 30 --health-mode adaptive --speed-check-every 0 --no-active-speed-when-passive-idle --min-mbps 0.5 --preferred-mbps 8 --max-latency-ms 2500 >> `"$Log`" 2>&1"
)
$lines | Set-Content -LiteralPath $Launcher -Encoding ASCII

# schtasks.exe mis-parses /TR values that contain embedded quotes, so register
# through the Task Scheduler cmdlets, which take the launcher path verbatim.
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c `"$Launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-Process -FilePath $Launcher -WindowStyle Hidden

Write-Host "Auto Guard task registered: $TaskName"
Write-Host "Launcher: $Launcher"
Write-Host "Log: $Log"
