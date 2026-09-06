@echo off
cd /d "%~dp0"
call SETUP_LOCAL.cmd
if errorlevel 1 (
  pause
  exit /b 1
)

echo Starting backend and frontend in separate windows...
start "MoodJournal Backend" cmd /k call "%~dp0START_BACKEND.cmd"
timeout /t 2 /nobreak >nul
start "MoodJournal Frontend" cmd /k call "%~dp0START_FRONTEND.cmd"
timeout /t 2 /nobreak >nul
start "" "http://localhost:5500/register.html"

echo.
echo MoodJournal started.
echo Close the Backend and Frontend windows when finished.
