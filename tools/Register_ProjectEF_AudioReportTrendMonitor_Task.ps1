$TaskName = "ProjectEF_AudioReportTrendMonitor"
$Root = "G:\AI\Material\Wwise"
$ReportRoot = Join-Path $Root ([string]([char]0x62A5) + [string]([char]0x544A))
$Script = Join-Path $env:USERPROFILE ".codex\skills\audio-report-trend-monitor\scripts\audio_report_trend_monitor.py"
$Python = "python"

if (-not (Test-Path -LiteralPath $Script)) {
    Write-Error "Missing trend monitor script: $Script"
    exit 1
}

$Args = @(
    "`"$Script`"",
    "--report-root", "`"$ReportRoot`"",
    "--latest", "12",
    "--max-file-mb", "200",
    "--out", "`"$ReportRoot\ProjectEF_AudioReport_TrendSummary.md`"",
    "--json-out", "`"$ReportRoot\ProjectEF_AudioReport_TrendSummary.json`""
) -join " "

$Action = New-ScheduledTaskAction -Execute $Python -Argument $Args -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 3) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "ProjectEF audio report trend monitor. Read-only. Runs every 3 hours." -Force
Write-Output "Registered scheduled task: $TaskName"
