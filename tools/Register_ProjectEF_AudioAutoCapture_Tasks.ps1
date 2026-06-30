param(
    [string]$DailyTime  = "19:30",
    [string]$WeeklyTime = "10:00",
    [string]$WeeklyDay  = "Monday"
)
$ErrorActionPreference = "Stop"
$Tools = $PSScriptRoot

# Resolve python / pythonw (pythonw = no console window for the background daemon)
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "python not found on PATH." }
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$daemon   = Join-Path $Tools "projectef_audio_autocapture_daemon.py"
$briefing = Join-Path $Tools "projectef_audio_briefing.py"

function Register-One($name, $exe, $argline, $trigger, $desc) {
    $action   = New-ScheduledTaskAction -Execute $exe -Argument $argline -WorkingDirectory $Tools
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description $desc -Force | Out-Null
    Write-Host "Registered: $name"
}

# 1) Auto-capture daemon — starts at logon, runs hidden in background
Register-One "ProjectEF_AudioAutoCaptureDaemon" $pythonw "-B `"$daemon`"" `
    (New-ScheduledTaskTrigger -AtLogOn) `
    "Auto-capture ProjectEF audio runtime logs per game session (background)."

# 2) Daily briefing
Register-One "ProjectEF_AudioBriefingDaily" $python "-B `"$briefing`" --period daily" `
    (New-ScheduledTaskTrigger -Daily -At $DailyTime) `
    "Generate ProjectEF daily audio runtime briefing (problems + suggested fixes)."

# 3) Weekly briefing
Register-One "ProjectEF_AudioBriefingWeekly" $python "-B `"$briefing`" --period weekly" `
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $WeeklyTime) `
    "Generate ProjectEF weekly audio runtime briefing (problems + suggested fixes)."

Write-Host ""
Write-Host "Done. Daemon auto-starts at next logon (or run the Control tool to start it now)."
Write-Host "Daily briefing @ $DailyTime ; Weekly briefing $WeeklyDay @ $WeeklyTime."
