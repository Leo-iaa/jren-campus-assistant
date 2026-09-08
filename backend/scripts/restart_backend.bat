@echo off
REM Restart the JREN backend so new code takes effect.
REM Run as Administrator (right-click > Run as administrator):
REM the backend runs as SYSTEM (started by the watchdog task), so a
REM normal user cannot kill it.
REM After the kill, the JrenBackendWatchdog task (every 15 min) notices
REM the port is free and starts the backend again with the new code.
REM On startup, the catch-up logic will push any pending WeChat
REM notifications (evening push after 21:05, etc.) automatically.
REM NOTE: keep this file ASCII-only (cmd.exe parses in ANSI codepage)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c:":28070 " ^| findstr /c:"LISTENING"') do taskkill /F /PID %%a

echo.
echo Backend process killed (if it was running).
echo The watchdog will restart it within 15 minutes; check backend\data\watchdog.log
pause
