param(
  [string]$TaskName = "ProjectEF_DailyAudioLogIntelligence"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
  Write-Host "Scheduled task '$TaskName' is not registered."
  exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Unregistered scheduled task '$TaskName'."
