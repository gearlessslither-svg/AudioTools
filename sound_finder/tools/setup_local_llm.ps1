param(
    [string]$PrimaryModel = "qwen2.5:7b-instruct",
    [string]$FallbackModel = "qwen2.5:3b-instruct",
    [switch]$SkipFallback
)

$ErrorActionPreference = "Stop"

function Test-Command {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Wait-Ollama {
    param([int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

if (!(Test-Command winget) -and !(Test-Command ollama)) {
    throw "Neither winget nor ollama is available. Install winget or Ollama first."
}

if (!(Test-Command ollama)) {
    Write-Host "Installing Ollama with winget..."
    winget install --id Ollama.Ollama -e --source winget --accept-package-agreements --accept-source-agreements --silent
}

if (!(Test-Command ollama)) {
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $candidate) {
        $env:PATH = "$(Split-Path -Parent $candidate);$env:PATH"
    }
}

if (!(Test-Command ollama)) {
    throw "Ollama install finished, but ollama.exe was not found on PATH."
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "Starting Ollama service..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
}

if (!(Wait-Ollama -Seconds 45)) {
    throw "Ollama did not become available at http://127.0.0.1:11434."
}

Write-Host "Pulling primary model: $PrimaryModel"
ollama pull $PrimaryModel

if (!$SkipFallback -and $FallbackModel) {
    Write-Host "Pulling fallback model: $FallbackModel"
    ollama pull $FallbackModel
}

Write-Host "Installed models:"
ollama list

Write-Host "Local LLM setup complete."
