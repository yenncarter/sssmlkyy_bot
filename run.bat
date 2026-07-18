@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo [ОШИБКА] Не найден venv\Scripts\python.exe
    echo Создай окружение: python -m venv venv
    echo Установи зависимости: venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo [ОШИБКА] Нет файла .env в папке beauty_bot
    echo Скопируй .env.example в .env и заполни BOT_TOKEN
    echo.
    pause
    exit /b 1
)

echo.
echo Останавливаю старые копии бота, если есть...
call "%~dp0_stop_instances.bat"
venv\Scripts\python.exe scripts\stop_bot.py >nul 2>&1
timeout /t 2 /nobreak >nul

echo Запуск Beauty Bot...
echo Держи только ОДНО это окно открытым.
echo.

venv\Scripts\python.exe main.py

echo.
if errorlevel 1 (
    echo Бот завершился с ошибкой.
) else (
    echo Бот остановлен.
)
echo.
pause
