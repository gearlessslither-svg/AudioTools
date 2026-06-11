$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Script = Join-Path $Root "Tools\projectef_daily_log_intelligence.py"
$ReportDirName = [string][char]0x62A5 + [string][char]0x544A
$ReportDir = Join-Path $Root $ReportDirName
$Today = Get-Date -Format "yyyy-MM-dd"
$OutMd = Join-Path $ReportDir "ProjectEF_DailyAudioLogIntelligence_$Today.md"
$OutJson = Join-Path $ReportDir "ProjectEF_DailyAudioLogIntelligence_$Today.json"

$env:PYTHONDONTWRITEBYTECODE = "1"

Write-Host "Root: $Root"
Write-Host "Report dir: $ReportDir"
Write-Host "Date: $Today"

python -B $Script `
  --report-root $ReportDir `
  --unity-root "D:\EF New\Client\TargetProject" `
  --wwise-root "D:\EF Wwise\ProjectEF" `
  --date $Today `
  --out $OutMd `
  --json-out $OutJson

if ($LASTEXITCODE -ne 0) {
  throw "projectef_daily_log_intelligence.py failed with exit code $LASTEXITCODE"
}

python -B (Join-Path $Root "Tools\render_projectef_reports_showcase.py")

if ($LASTEXITCODE -ne 0) {
  throw "render_projectef_reports_showcase.py failed with exit code $LASTEXITCODE"
}
