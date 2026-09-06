@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo MoodJournal - Local Setup (RAM, no AWS)
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python 3.14 virtual environment...
  py -3.14 -m venv .venv
  if errorlevel 1 (
    echo.
    echo ERROR: Python 3.14 was not found.
    echo Check with: py -0p
    exit /b 1
  )
)

echo Installing local dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r backend\requirements-local.txt
if errorlevel 1 exit /b 1

if not exist ".env" (
  copy /Y ".env.local.example" ".env" >nul
  echo Created .env from .env.local.example
)

echo.
echo Setup complete.
exit /b 0
