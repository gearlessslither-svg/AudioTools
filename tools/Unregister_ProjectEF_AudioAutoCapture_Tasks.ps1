$ErrorActionPreference = "SilentlyContinue"
foreach ($name in @("ProjectEF_AudioAutoCaptureDaemon", "ProjectEF_AudioBriefingDaily", "ProjectEF_AudioBriefingWeekly")) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed (if existed): $name"
}
