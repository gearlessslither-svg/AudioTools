param(
  [string]$TaskName = "ProjectEF_DailyAudioLogIntelligence",
  [string]$Time = "23:50"
)

$ErrorActionPreference = "Stop"

$scriptRoot = "G:\AI\Material\Wwise"
$launcher = Join-Path $scriptRoot "Tools\Start_ProjectEF_DailyLogIntelligence_Once.ps1"

if (-not (Test-Path -LiteralPath $launcher)) {
  throw "Launcher not found: $launcher"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`"" `
  -WorkingDirectory $scriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Generate ProjectEF daily audio log intelligence report and refresh dashboard." `
  -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' at $Time."
