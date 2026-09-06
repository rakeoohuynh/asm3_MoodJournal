@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call SETUP_LOCAL.cmd
  if errorlevel 1 (
  pause
  exit /b 1
)
)

echo.
echo ==========================================
echo MoodJournal Local Frontend
echo ==========================================
echo Frontend: http://localhost:5500
echo Register: http://localhost:5500/register.html
echo ==========================================
echo.
".venv\Scripts\python.exe" -m http.server 5500 --directory frontend
