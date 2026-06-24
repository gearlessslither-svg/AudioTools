$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $env:LOCALAPPDATA "MullvadSpeedGuard"
$TaskName = "MullvadSpeedGuardAutoGuard"

schtasks /End /TN $TaskName | Out-Null
schtasks /Delete /TN $TaskName /F | Out-Null

$pidFiles = @(
  (Join-Path $Root "results\auto_guard.pid"),
  (Join-Path $Runtime "results\auto_guard.pid")
)

foreach ($pidFile in $pidFiles) {
  if (Test-Path -LiteralPath $pidFile) {
    $pidValue = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidValue -match '^\d+$') {
      Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "Auto Guard task removed: $TaskName"
