@echo off
cd /d "%~dp0"
call SETUP_LOCAL.cmd
if errorlevel 1 (
  pause
  exit /b 1
)

echo.
echo ==========================================
echo MoodJournal Local Backend
echo ==========================================
echo Backend: http://127.0.0.1:8000
echo Health:  http://127.0.0.1:8000/health
echo Data:    RAM only - restart clears data
echo AWS:     OFF
echo ==========================================
echo.
".venv\Scripts\python.exe" -m uvicorn backend.local_app:app --host 127.0.0.1 --port 8000 --reload
