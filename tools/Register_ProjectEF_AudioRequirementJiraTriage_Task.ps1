param(
    [string]$TaskName = "ProjectEF_AudioRequirementJiraTriage_ScanDiff",
    [string]$At = "10:00",
    [string]$Launcher = "G:\AI\Material\Wwise\Tools\Start_ProjectEF_AudioRequirementJiraTriage_ScanDiff_Once.cmd"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Launcher not found: $Launcher"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Launcher`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -Compatibility Win8 -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Read-only ProjectEF design-doc audio requirement scan and diff report." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "Daily time: $At"
Write-Host "Launcher: $Launcher"
