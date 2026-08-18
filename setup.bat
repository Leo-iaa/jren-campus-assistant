@echo off
setlocal
title Jren Campus Assistant - Setup
cd /d "%~dp0"

echo ============================================
echo   Jren Campus Assistant - One-Click Setup
echo ============================================
echo.

REM ---------- Step 1: find a working Python ----------
REM The Microsoft Store "App Execution Alias" (WindowsApps\python.exe)
REM can shadow the real Python and silently do nothing. So we probe
REM python first; if it produces no output, fall back to the py launcher.
echo [1/4] Checking Python...

set "PYCMD="
set "PROBE="
for /f "delims=" %%i in ('python -c "import sys; print(1)" 2^>nul') do set "PROBE=%%i"
if "%PROBE%"=="1" set "PYCMD=python"
if defined PYCMD goto :py_found

set "PROBE="
for /f "delims=" %%i in ('py -3 -c "import sys; print(1)" 2^>nul') do set "PROBE=%%i"
if "%PROBE%"=="1" set "PYCMD=py -3"
if defined PYCMD goto :py_found

goto :no_python

:py_found
set "PYVER="
for /f "delims=" %%v in ('%PYCMD% -c "import sys; print(sys.version.split()[0])" 2^>^&1') do set "PYVER=%%v"
echo       Using: %PYCMD%   (Python %PYVER%)
echo.

REM ---------- Step 2: create venv ----------
if exist ".venv\Scripts\python.exe" (
    echo [2/4] .venv already exists, skipping.
    goto :install_deps
)
echo [2/4] Creating virtual environment (.venv)...
%PYCMD% -m venv .venv
if errorlevel 1 goto :venv_failed
if not exist ".venv\Scripts\python.exe" goto :venv_failed
echo.

:install_deps
echo [3/4] Installing dependencies (may take a few minutes)...
set "PYTHONUTF8=1"
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r backend\requirements.txt
if errorlevel 1 goto :pip_failed
echo.

echo [4/4] Initializing database...
python -m backend.scripts.init_db
if errorlevel 1 goto :db_failed
echo.

echo ============================================
echo   Setup complete!
echo.
echo   Next steps:
echo     1. Double-click  backend\scripts\start_backend.bat
echo        (or run: uvicorn backend.main:app --host 0.0.0.0 --port 8000)
echo     2. Health check:  http://127.0.0.1:8000/health
echo     3. Follow the user manual: docs/USER_GUIDE.md
echo ============================================
echo.
pause
exit /b 0

:no_python
echo.
echo ERROR: No working Python found.
echo.
echo The 'python' command is likely shadowed by the Microsoft Store
echo placeholder (it exists but does nothing). Fix it in one of two ways:
echo.
echo   Option A (recommended): turn off the fake alias
echo     Win+R  -^>  ms-settings:appexecutionaliases
echo     Turn OFF both "python.exe" and "python3.exe"
echo     Then close this window and run setup.bat again.
echo.
echo   Option B: install real Python
echo     winget install Python.Python.3.12
echo.
pause
exit /b 1

:venv_failed
echo.
echo ERROR: Failed to create virtual environment.
echo 'python' may be the Store placeholder. Turn off the alias
echo (Win+R -^> ms-settings:appexecutionaliases) or run: py -3 -m venv .venv
echo.
pause
exit /b 1

:pip_failed
echo.
echo ERROR: Failed to install dependencies. Check your network and retry.
echo.
pause
exit /b 1

:db_failed
echo.
echo ERROR: Database initialization failed.
echo.
pause
exit /b 1
