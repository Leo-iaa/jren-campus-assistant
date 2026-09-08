@echo off
REM Registers the Jren backend watchdog into Windows Task Scheduler.
REM Run ONCE, as Administrator (right-click > Run as administrator).
REM Every 15 minutes the watchdog checks port 28070 and restarts
REM uvicorn if it is down.
REM Registered as SYSTEM (session 0, never pops a window) AND with
REM battery-safe + StartWhenAvailable settings. Without those, the
REM trigger is silently SKIPPED while the laptop runs on battery -
REM this left the backend dead all evening on 2026-09-06.
REM NOTE: keep this file ASCII-only (cmd.exe parses in ANSI codepage)

powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute 'C:\Users\LEO\jren-campus-assistant\backend\scripts\jren_watchdog.bat'; $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650); $p = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest; $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1); Register-ScheduledTask -TaskName 'JrenBackendWatchdog' -Action $a -Trigger $t -Principal $p -Settings $s -Force"

if errorlevel 1 (
  echo.
  echo Failed to register task. Run this script as Administrator.
  pause
  exit /b 1
)

echo.
echo Task "JrenBackendWatchdog" registered: every 15 min, SYSTEM context,
echo runs on battery, catches up missed triggers.
echo The watchdog restarts uvicorn when port 28070 is not listening,
echo and logs every decision to backend\data\watchdog.log.
echo.
echo To remove:  schtasks /delete /tn "JrenBackendWatchdog" /f
pause
