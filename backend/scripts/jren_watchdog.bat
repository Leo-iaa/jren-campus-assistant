@echo off
REM JREN Campus Assistant server watchdog (batch). Restarts uvicorn if port 28070 not listening.
set PORT=28070
netstat -ano 2>nul | findstr ":28070 " | findstr "LISTENING" >nul
if %errorlevel%==0 exit /b 0
cd /d C:\Users\LEO\jren-campus-assistant
start "" /min cmd /c "C:\Users\LEO\jren-campus-assistant\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 28070 >> C:\Users\LEO\jren-campus-assistant\backend\data\server.log 2>&1"
exit /b 0
