@echo off
rem Запуск сервера «Мозаика» на Windows.
rem Кодировка консоли переключается на UTF-8, чтобы русский текст
rem в журнале отображался корректно.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py"
) else (
    set "PYTHON=python"
)

echo Запуск сервера на порту 8000...
%PYTHON% server/main.py --host 0.0.0.0 --port 8000 %*
pause
