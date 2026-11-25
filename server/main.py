#!/usr/bin/env python3
"""Точка входа сервера «Мозаика».

Запуск из корня проекта::

    python server/main.py --host 0.0.0.0 --port 8000

Скрипт можно запускать и как модуль::

    python -m server.main --port 8000

Здесь настраиваются журналы, создаётся приложение, запускается TCP-сервер
и печатается баннер с адресами для локальной сети.
"""

from __future__ import annotations

import logging
import os
import socket
import sys

# При запуске файлом Python кладёт каталог server/ в начало sys.path.
# Из-за этого пакет server.http затенял бы стандартный модуль http,
# поэтому убираем каталог из пути и добавляем корень проекта.
if __package__ in (None, ""):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _ROOT = os.path.dirname(_HERE)
    if sys.path and os.path.abspath(sys.path[0]) == _HERE:
        del sys.path[0]
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from server.app import Application  # noqa: E402
from server.config import Config, describe, load_config  # noqa: E402
from server.core import network  # noqa: E402
from server.core.logging_setup import (  # noqa: E402
    close_logging,
    setup_logging,
)
from server.core.server import HTTPServer  # noqa: E402

server_logger = logging.getLogger("mosaic.server")


def local_addresses() -> list[str]:
    """IPv4-адреса машины, отсортированные по вероятности.

    Returns:
        Список адресов: первым идёт наиболее вероятный адрес Wi-Fi
        или Ethernet, виртуальные адаптеры — в конце.
    """
    return network.local_addresses()


def print_banner(config: Config, port: int) -> None:
    """Печатает адреса, по которым доступен сервер.

    Args:
        config: конфигурация (нужна для путей к базе и файлам).
        port: фактический порт, на котором слушает сервер.
    """
    print("=" * 56)
    print("  Мозаика — сервер запущен")
    print("=" * 56)
    print(f"  На этом ПК:      http://127.0.0.1:{port}")
    addresses = local_addresses()
    if addresses:
        print(f"  С другого ПК:    http://{addresses[0]}:{port}")
    for address in addresses[1:]:
        print(f"  Другой адрес:    http://{address}:{port}")
    print(f"  База:            {config.db_path}")
    print(f"  Файлы:           {config.uploads_dir}")
    print(f"  Журнал:          {config.log_path} ({config.log_level})")
    print("  Остановка:       Ctrl+C")
    print("=" * 56)
    print("  Для доступа со второго ПК разрешите порт: "
          "scripts\\start_server_public.bat")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    """Запускает сервер и работает до Ctrl+C.

    Args:
        argv: аргументы командной строки без имени программы; None —
            взять sys.argv[1:].

    Returns:
        Код возврата: 0 при штатной остановке, 1 при занятом порте.
    """
    # На русской Windows консоль по умолчанию не в UTF-8, из-за чего
    # русский текст в журнале превращается в мусор. Переключаем потоки.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    config = load_config(argv).ensure_dirs()
    setup_logging(config)

    server_logger.info("Запуск: Python %s", sys.version.split()[0])
    server_logger.info("Конфигурация: %s", describe(config))
    print(f"Конфигурация: {describe(config)}")
    sys.stdout.flush()

    application = Application(config)
    server = HTTPServer(config, application)
    try:
        server.start()
    except OSError as exc:
        server_logger.error("Не удалось занять %s:%s: %s",
                            config.host, config.port, exc)
        print(f"Не удалось занять {config.host}:{config.port}: {exc}",
              file=sys.stderr)
        print("Возможно, порт уже занят. Укажите другой: --port 8001",
              file=sys.stderr)
        application.close()
        close_logging()
        return 1

    print_banner(config, server.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
    finally:
        server.shutdown()
        application.close()
        server_logger.info("Сервер остановлен")
        close_logging()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
