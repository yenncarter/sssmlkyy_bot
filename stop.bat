@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo Останавливаю бота...
echo.

call "%~dp0_stop_instances.bat"
venv\Scripts\python.exe scripts\stop_bot.py

echo.
echo Готово. Теперь запусти run.bat — только один раз.
echo.
pause
