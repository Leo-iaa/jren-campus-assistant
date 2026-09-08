@echo off
REM JREN Campus Assistant server watchdog (batch). Restarts uvicorn if port 28070 not listening.
REM Registered via register_watchdog_task.bat (Task Scheduler, every 15 min).
REM NOTE: keep this file ASCII-only (cmd.exe parses in ANSI codepage)
REM Self-logging: every run appends its decision to watchdog.log so a
REM silent failure (skipped trigger, failed start) leaves evidence.
>> "C:\Users\LEO\jren-campus-assistant\backend\data\watchdog.log" echo [%date% %time%] check begin
netstat -ano 2>nul | findstr /c:":28070 " | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
  >> "C:\Users\LEO\jren-campus-assistant\backend\data\watchdog.log" echo [%date% %time%] port up, no action
  exit /b 0
)
>> "C:\Users\LEO\jren-campus-assistant\backend\data\watchdog.log" echo [%date% %time%] port DOWN, starting uvicorn

cd /d C:\Users\LEO\jren-campus-assistant
REM PYTHONUTF8=1: force UTF-8 stdio so server.log stays single-encoding;
REM append-only redirect (>>) - never overwrite server.log
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  start "" /min cmd /c "".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 28070 >> "backend\data\server.log" 2>&1"
) else (
  start "" /min cmd /c "py -3 -m uvicorn backend.main:app --host 0.0.0.0 --port 28070 >> "backend\data\server.log" 2>&1"
)
exit /b 0
