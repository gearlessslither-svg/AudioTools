$ErrorActionPreference = "Stop"

$python = "python"
$auditScript = "C:\Users\user1\.codex\skills\unity-wwise-runtime-log-audit\scripts\unity_wwise_runtime_log_audit.py"
$unityRoot = "D:\EF New\Client\TargetProject"
$wwiseRoot = "D:\EF Wwise\ProjectEF"
$outDir = "G:\AI\Material\Wwise"
$report = Join-Path $outDir "ProjectEF_UnityWwise_RuntimeAudioFollow.md"
$json = Join-Path $outDir "ProjectEF_UnityWwise_RuntimeAudioFollow.json"
$jsonl = Join-Path $outDir "ProjectEF_UnityWwise_RuntimeAudioFollow.jsonl"

if (-not (Test-Path $auditScript)) {
    throw "Audit script not found: $auditScript"
}
if (-not (Test-Path $unityRoot)) {
    throw "Unity project not found: $unityRoot"
}
if (-not (Test-Path $wwiseRoot)) {
    throw "Wwise project not found: $wwiseRoot"
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Host "ProjectEF Unity/Wwise runtime audio follow"
Write-Host "Status: running in read-only log follow mode"
Write-Host "Unity:  $unityRoot"
Write-Host "Wwise:  $wwiseRoot"
Write-Host "Report: $report"
Write-Host ""
Write-Host "Keep this window open while testing in Unity."
Write-Host "Press Ctrl+C or close this window to stop."
Write-Host ""

& $python -X utf8 $auditScript `
  --unity-root $unityRoot `
  --wwise-project-root $wwiseRoot `
  --out $report `
  --json-out $json `
  --jsonl-out $jsonl `
  --follow `
  --print-all-audio
