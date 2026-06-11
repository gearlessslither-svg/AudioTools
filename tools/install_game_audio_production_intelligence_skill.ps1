$ErrorActionPreference = "Stop"

$source = "G:\AI\Material\Wwise\skills\game-audio-production-intelligence"
$targetRoot = "$env:USERPROFILE\.codex\skills"
$target = Join-Path $targetRoot "game-audio-production-intelligence"

if (-not (Test-Path $source)) {
    throw "Source skill not found: $source"
}

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
Copy-Item -Path $source -Destination $targetRoot -Recurse -Force

Write-Host "Installed skill to: $target"
Get-ChildItem -Recurse $target | Select-Object FullName,Length
