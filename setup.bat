@echo off
setlocal
title Jren Campus Assistant - Setup
cd /d "%~dp0"

echo ============================================
echo   Jren Campus Assistant - One-Click Setup
echo ============================================
echo.

REM ---------- Step 1: check Python ----------
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 goto :no_python
set "PYCHECK="
for /f "delims=" %%i in ('python --version 2^>^&1') do set "PYCHECK=%%i"
echo       Found: %PYCHECK%
echo.
if not exist ".venv\Scripts\python.exe" goto :create_venv
echo       .venv already exists, skipping creation.
goto :install_deps

:create_venv
echo [2/4] Creating virtual environment (.venv)...
python -m venv .venv
if errorlevel 1 goto :venv_failed
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
echo ERROR: Python not found or not working.
echo If you only see "Python was not found", your 'python' is the
echo Microsoft Store placeholder. Install real Python first:
echo.
echo     winget install Python.Python.3.12
echo.
echo Then close this window and run setup.bat again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo ERROR: Failed to create virtual environment.
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
