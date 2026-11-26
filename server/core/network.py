"""Сетевые адреса компьютера и их приоритет.

Один и тот же список используют и баннер сервера, и скрипт проверки
сети, чтобы студент видел один и тот же рекомендованный адрес.
"""

from __future__ import annotations

import socket


def address_priority(address: str) -> int:
    """Условный рейтинг адреса: меньше — вероятнее рабочая локальная сеть.

    Один компьютер обычно имеет несколько IPv4-адресов: Wi-Fi или
    Ethernet, loopback, адаптеры VMware/VirtualBox, VPN и Docker.
    Для баннера и проверки сети нужно поднимать наверх адрес, по
    которому действительно можно подключиться с телефона или второго
    ноутбука. Поэтому известные виртуальные подсети получают худший
    рейтинг, а обычные домашние и корпоративные сети — лучший.

    Args:
        address: IPv4-адрес.

    Returns:
        Число от 0 (лучший) до 9 (непригодный).
    """
    octets = address.split(".")
    try:
        second = int(octets[1])
    except (IndexError, ValueError):
        return 9

    # Служебные и заведомо виртуальные адреса: loopback, APIPA,
    # host-only сети VMware и мосты Docker/VPN.
    if address.startswith(("127.", "169.254.")):
        return 9
    if address.startswith(("192.168.197.", "192.168.253.",
                           "172.17.", "172.18.")):
        return 9

    if address.startswith(("192.168.0.", "192.168.1.")):
        return 0
    if address.startswith("10."):
        return 1
    if address.startswith("192.168."):
        return 1
    if octets[0] == "172" and 16 <= second <= 31:
        return 6
    return 3


def local_addresses() -> list[str]:
    """IPv4-адреса машины, отсортированные по вероятности.

    Returns:
        Список адресов без loopback: первым идёт наиболее вероятный
        адрес домашней сети.
    """
    result: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            result.add(info[4][0])
    except OSError:
        pass
    result.discard("127.0.0.1")

    def sort_key(item: str) -> tuple[int, tuple[int, ...], str]:
        try:
            parts = tuple(int(part) for part in item.split("."))
        except ValueError:
            parts = (999, 999, 999, 999)
        return (address_priority(item), parts, item)

    return sorted(result, key=sort_key)
