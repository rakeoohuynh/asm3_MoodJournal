@echo off
cd /d "%~dp0"
call SETUP_LOCAL.cmd
if errorlevel 1 (
  pause
  exit /b 1
)
set APP_ENV=local
set JWT_SECRET=local-test-secret-at-least-32-bytes-long
set GEMINI_API_KEY=
".venv\Scripts\python.exe" -m pytest -q tests\test_local_app.py
pause
