@echo off
REM ============================================================
REM  jren-campus-assistant backend startup script (Windows)
REM  Triggered at logon by startup-folder vbs (hidden window)
REM  Log: backend\data\server.log
REM  NOTE: keep this file ASCII-only (cmd.exe parses in ANSI codepage)
REM ============================================================

REM cd to repo root (this script lives in backend\scripts\)
cd /d "%~dp0..\.."

REM skip if port 28070 is already listening (avoid double start)
netstat -ano | findstr /c:":28070 " | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [%date% %time%] port 28070 already in use, skip start >> "backend\data\server.log" 2>nul
  exit /b 0
)

REM ---- optional: Notion calendar database id (used by confirm_plan) ----
REM either uncomment and fill below, or set config.calendar_database_id
REM set JREN_NOTION_CALENDAR_DB=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

REM ---- start backend ----
REM PYTHONUTF8=1: force UTF-8 stdio so server.log stays single-encoding
echo [%date% %time%] starting uvicorn >> "backend\data\server.log" 2>nul
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 28070 >> "backend\data\server.log" 2>&1
) else (
  py -3 -m uvicorn backend.main:app --host 0.0.0.0 --port 28070 >> "backend\data\server.log" 2>&1
)
