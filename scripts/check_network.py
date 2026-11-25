#!/usr/bin/env python3
"""Проверка доступности сервера «Мозаика» с других устройств.

Скрипт показывает, запущен ли сервер, есть ли правило брандмауэра,
какие у компьютера адреса и по какому из них открывается сайт.

Запуск (сервер при этом должен работать):
    py scripts/check_network.py
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.core.network import address_priority, local_addresses  # noqa: E402

PORT = 8000


def port_open(host: str, port: int = PORT, timeout: float = 0.7) -> bool:
    """Проверяет, принимает ли адрес TCP-подключения."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def firewall_rule_exists() -> bool:
    """Есть ли правило Mosaic 8000 (exit code netsh не зависит от языка)."""
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=Mosaic 8000"],
            capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def classify(address: str) -> str:
    """Поясняет, что это за адрес."""
    priority = address_priority(address)
    if priority == 9:
        return "автоматический адрес (сеть не настроена)"
    if priority == 0:
        return "локальная сеть — подходит для второго устройства"
    if priority == 1:
        return "локальная сеть 10.x — подходит"
    if priority == 2:
        return "возможно, виртуальный адаптер (VMware/VirtualBox)"
    if priority == 5:
        return "виртуальный адаптер (Docker/WSL)"
    return "другой интерфейс"


def preferred(addresses: list[str]) -> str:
    """Первый адрес в порядке приоритета (список уже отсортирован)."""
    return addresses[0]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  Мозаика — проверка сети")
    print("=" * 60)

    server_running = port_open("127.0.0.1")
    print(f"  Сервер на порту {PORT}:        "
          + ("работает" if server_running else "НЕ ЗАПУЩЕН"))
    if not server_running:
        print("  Сначала запустите scripts\\start_server_public.bat")

    rule = firewall_rule_exists()
    print("  Правило брандмауэра:          "
          + ("есть" if rule else "НЕТ — запустите scripts\\start_server_public.bat"))
    print()

    addresses = local_addresses()
    if not addresses:
        print("  Не найдено ни одного сетевого адреса.")
        print("  Проверьте, что компьютер подключён к Wi-Fi или кабелю.")
        return 1

    print("  Адреса компьютера:")
    candidates: list[str] = []
    for address in addresses:
        answers = port_open(address)
        mark = "сервер отвечает" if answers else "не отвечает"
        print(f"    http://{address}:{PORT:<5} {mark:16s} {classify(address)}")
        if answers:
            candidates.append(address)

    print()
    if candidates:
        best = preferred(candidates)
        print(f"  Откройте на другом устройстве:  http://{best}:{PORT}")
    else:
        print("  Ни один адрес не принял подключение.")
        print("  Похоже, сервер не запущен или слушает только 127.0.0.1.")

    print()
    print("  Если с другого устройства не открывается:")
    print("   1. Устройства должны быть в одной сети (не в гостевой Wi-Fi).")
    print("   2. Проверьте связь: ping <адрес> с другого устройства.")
    print("   3. Запустите scripts\\start_server_public.bat (правило + сервер).")
    print("   4. Точка доступа телефона или кабель обходят изоляцию клиентов.")
    print("   5. Если выбран адрес виртуального адаптера, возьмите адрес")
    print("      Wi-Fi/Ethernet из строки, где написано «подходит».")
    print("   6. Из интернета этот адрес недоступен: нужен туннель или хостинг.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
