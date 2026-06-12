$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$Stamp = Join-Path $Venv ".requirements.sha256"

if (!(Test-Path $Python)) {
    python -m venv $Venv
}

$CurrentHash = (Get-FileHash $Requirements -Algorithm SHA256).Hash
$InstalledHash = if (Test-Path $Stamp) { Get-Content $Stamp -ErrorAction SilentlyContinue } else { "" }

if ($CurrentHash -ne $InstalledHash) {
    & $Python -m pip install -r $Requirements
    try {
        Set-Content -Path $Stamp -Value $CurrentHash -ErrorAction Stop
    } catch {
        # Another launcher may have written the stamp concurrently.
    }
}

if ($args -contains "--obs-reaper-bridge") {
    & $Python (Join-Path $Root "tools\obs_reaper_bridge.py")
    exit $LASTEXITCODE
}

$env:PYTHONPATH = Join-Path $Root "src"
& $Python -m sound_finder @args
exit $LASTEXITCODE
