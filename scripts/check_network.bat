@echo off
rem Проверка, почему сайт не открывается с другого устройства.
rem Запускайте при работающем сервере.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (
    py scripts/check_network.py
) else (
    python scripts/check_network.py
)

echo.
pause
