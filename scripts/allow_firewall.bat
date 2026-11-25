@echo off
rem Разрешает входящие подключения к серверу «Мозаика» на порт 8000.
rem Запускать двойным щелчком; при запросе UAC подтвердите права администратора.
chcp 65001 >nul
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Требуются права администратора. Открываем новое окно с повышением...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

netsh advfirewall firewall delete rule name="Mosaic 8000" >nul 2>&1
netsh advfirewall firewall add rule name="Mosaic 8000" dir=in action=allow protocol=TCP localport=8000 >nul
if %errorlevel%==0 (
    echo Готово: входящие подключения на порт 8000 разрешены.
    echo Теперь второй компьютер может открыть http://IP-сервера:8000
) else (
    echo Не удалось добавить правило. Попробуйте выполнить файл от имени администратора.
)

echo.
echo IP-адреса этого компьютера:
ipconfig | findstr /i "IPv4"
echo.
pause
