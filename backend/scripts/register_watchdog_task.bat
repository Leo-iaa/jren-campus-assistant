@echo off
REM Registers the Jren backend watchdog into Windows Task Scheduler.
REM Run ONCE, as Administrator. Every 15 minutes the watchdog checks
REM port 28070 and restarts uvicorn if it is down.
REM Registered as SYSTEM (session 0): the watchdog NEVER opens a window
REM on your desktop, so it will not interrupt games or presentations.
REM NOTE: keep this file ASCII-only (cmd.exe parses in ANSI codepage)

schtasks /create /tn "JrenBackendWatchdog" /tr "\"C:\Users\LEO\jren-campus-assistant\backend\scripts\jren_watchdog.bat\"" /sc minute /mo 15 /ru SYSTEM /f
if errorlevel 1 (
  echo.
  echo Failed to register task. Run this script as Administrator.
  pause
  exit /b 1
)

echo.
echo Task "JrenBackendWatchdog" registered successfully (every 15 minutes, SYSTEM context).
echo The watchdog restarts uvicorn when port 28070 is not listening.
echo SYSTEM tasks run headless - no window will ever pop up.
echo.
schtasks /query /tn "JrenBackendWatchdog"
echo.
echo To remove:  schtasks /delete /tn "JrenBackendWatchdog" /f
pause
