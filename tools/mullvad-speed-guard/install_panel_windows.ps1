$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $env:LOCALAPPDATA "MullvadSpeedGuard"
$Results = Join-Path $Runtime "results"
$Launcher = Join-Path $Runtime "run_panel.cmd"
$Log = Join-Path $Results "panel_supervisor.log"
$TaskName = "MullvadSpeedGuardPanel"

New-Item -ItemType Directory -Force -Path $Results | Out-Null

$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = if ($python) {
  '"' + $python.Source + '"'
} else {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if (-not $py) { throw "Python 3 was not found. Install Python 3 and try again." }
  '"' + $py.Source + '" -3'
}

$script = Join-Path $Root "guard_panel_server.py"
$lines = @(
  "@echo off",
  "cd /d `"$Root`"",
  "$prefix `"$script`" --port 18790 >> `"$Log`" 2>&1"
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
Start-Process "http://127.0.0.1:18790/"

Write-Host "Panel task registered: $TaskName"
Write-Host "Launcher: $Launcher"
Write-Host "Log: $Log"
