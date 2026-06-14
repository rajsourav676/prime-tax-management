@echo off
cd /d "%~dp0"
echo Installing Flask for Prime Tax Management...
py -m pip install -r requirements.txt
if errorlevel 1 python -m pip install -r requirements.txt
pause
