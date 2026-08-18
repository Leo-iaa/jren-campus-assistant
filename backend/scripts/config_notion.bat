@echo off
title Jren Campus Assistant - Notion Config
cd /d "%~dp0..\.."
if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" backend\scripts\config_notion.py
) else (
  py -3 backend\scripts\config_notion.py
)
