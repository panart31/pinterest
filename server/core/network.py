"""Сетевые адреса компьютера и их приоритет.

Один и тот же список используют и баннер сервера, и скрипт проверки
сети, чтобы студент видел один и тот же рекомендованный адрес.
"""

from __future__ import annotations

import socket


def address_priority(address: str) -> int:
    """Условный рейтинг адреса: меньше — вероятнее домашняя сеть.

    Порядок выбран эмпирически: типичные домашние сети 192.168.0.x и
    192.168.1.x идут первыми, затем 10.x, затем прочие 192.168.x
    (часто это VMware/VirtualBox), затем виртуальные мосты Docker/WSL.

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
    if address.startswith(("127.", "169.254.")):
        return 9
    if address.startswith(("192.168.0.", "192.168.1.")):
        return 0
    if address.startswith("10."):
        return 1
    if address.startswith("192.168."):
        return 2
    if octets[0] == "172" and 16 <= second <= 31:
        return 5
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
    return sorted(result, key=lambda item: (address_priority(item), item))
