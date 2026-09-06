$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== MoodJournal local frontend ===" -ForegroundColor Cyan

if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

Set-Location frontend
Write-Host "Frontend: http://localhost:5500" -ForegroundColor Green
Write-Host "Register: http://localhost:5500/register.html" -ForegroundColor Green
Write-Host "Keep this window open." -ForegroundColor Yellow

python -m http.server 5500
