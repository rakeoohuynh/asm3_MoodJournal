$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== MoodJournal local backend (RAM, no AWS) ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python 3.14 virtual environment..."
    py -3.14 -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements-local.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.local.example .env
    Write-Host "Created .env from .env.local.example"
}

Write-Host ""
Write-Host "Backend: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Health:  http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host "Keep this window open." -ForegroundColor Yellow
Write-Host "Then open a SECOND PowerShell and run: .\START_FRONTEND.ps1" -ForegroundColor Yellow
Write-Host ""

python -m uvicorn backend.local_app:app --host 127.0.0.1 --port 8000 --reload
