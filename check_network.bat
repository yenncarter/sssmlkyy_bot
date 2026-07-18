@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python scripts\check_connection.py
pause
