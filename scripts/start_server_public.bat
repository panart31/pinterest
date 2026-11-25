@echo off
rem Запуск сервера «Мозаика» в режиме для нескольких устройств.
rem Один раз запрашивает права администратора, добавляет правило
rem брандмауэра для порта 8000 и запускает сервер на 0.0.0.0.
chcp 65001 >nul
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Для доступа с других устройств нужно разрешить порт в брандмауэре.
    echo Открываем окно с правами администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

netsh advfirewall firewall delete rule name="Mosaic 8000" >nul 2>&1
netsh advfirewall firewall add rule name="Mosaic 8000" dir=in action=allow protocol=TCP localport=8000 >nul
echo Правило брандмауэра для порта 8000 добавлено.
echo.
echo IP-адреса этого компьютера:
ipconfig | findstr /i "IPv4"
echo.

cd /d "%~dp0.."
set PYTHONUTF8=1
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py"
) else (
    set "PYTHON=python"
)

echo Запуск сервера на порту 8000...
%PYTHON% server/main.py --host 0.0.0.0 --port 8000 %*
pause
