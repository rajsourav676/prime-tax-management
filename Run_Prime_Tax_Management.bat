@echo off
title Prime Tax Management
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Please install Python 3 first.
  pause
  exit /b
)
start http://127.0.0.1:5000
python app.py
pause
