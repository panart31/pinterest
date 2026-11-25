"""Конфигурация сервера «Мозаика».

Источники настроек (по убыванию приоритета):
1. аргументы командной строки;
2. файл config.json;
3. значения по умолчанию из dataclass ``Config``.

Относительные пути в config.json отсчитываются от корня проекта,
а не от текущего каталога, поэтому сервер можно запускать из любого места.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config.json"

# Поля, которые разрешено переопределять из config.json.
_PATH_FIELDS = ("db_path", "uploads_dir", "web_dir", "log_path")

_MEGABYTE = 1024 * 1024


@dataclass(frozen=True)
class Config:
    """Все настройки сервера в одном неизменяемом объекте."""

    host: str = "0.0.0.0"
    port: int = 8000
    db_path: Path = PROJECT_ROOT / "storage" / "mosaic.db"
    uploads_dir: Path = PROJECT_ROOT / "storage" / "uploads"
    web_dir: Path = PROJECT_ROOT / "web"
    log_path: Path = PROJECT_ROOT / "server.log"

    # Лимиты, защищающие сервер от перегрузки.
    max_upload: int = 5 * _MEGABYTE
    max_body: int = 6 * _MEGABYTE
    max_header: int = 16 * 1024

    timeout: float = 30.0
    session_days: int = 7
    backlog: int = 64
    log_level: str = "INFO"

    def ensure_dirs(self) -> "Config":
        """Создаёт каталоги для БД и загруженных файлов.

        Returns:
            Тот же объект Config (удобно для цепочки вызовов).
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        return self


def _field_names() -> set[str]:
    return {field.name for field in fields(Config)}


def _to_path(value: Any, base: Path) -> Path:
    """Превращает значение из JSON в абсолютный путь."""
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def read_config_file(path: Path) -> dict[str, Any]:
    """Читает config.json и отбрасывает неизвестные ключи.

    Args:
        path: Путь к JSON-файлу.

    Returns:
        Словарь известных полей Config; пустой, если файла нет.

    Raises:
        SystemExit: если файл повреждён или содержит не объект.
    """
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Не удалось прочитать конфигурацию {path}: {exc}")
    if not isinstance(raw, dict):
        raise SystemExit(f"Конфигурация {path} должна быть JSON-объектом")

    known = _field_names()
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known:
            continue
        if key in _PATH_FIELDS:
            result[key] = _to_path(value, PROJECT_ROOT)
        else:
            result[key] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов командной строки.

    Returns:
        Настроенный ArgumentParser со всеми параметрами сервера.
    """
    parser = argparse.ArgumentParser(
        prog="server.main",
        description="Сервер «Мозаика»: HTTP/1.1 поверх TCP-сокетов",
    )
    parser.add_argument("--host", help="адрес прослушивания (по умолчанию 0.0.0.0)")
    parser.add_argument("--port", type=int, help="порт (по умолчанию 8000)")
    parser.add_argument("--db", dest="db_path", help="путь к файлу SQLite")
    parser.add_argument("--uploads", dest="uploads_dir", help="каталог загруженных файлов")
    parser.add_argument("--web", dest="web_dir", help="каталог статических файлов")
    parser.add_argument("--log", dest="log_path", help="путь к файлу журнала")
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        type=str.upper, help="подробность журнала (по умолчанию INFO)")
    parser.add_argument("--max-upload", type=int, help="предельный размер файла в байтах")
    parser.add_argument("--config", help="путь к config.json")
    return parser


def load_config(argv: Iterable[str] | None = None) -> Config:
    """Собирает итоговую конфигурацию из трёх источников.

    Приоритет: аргументы командной строки > config.json > умолчания.

    Args:
        argv: Аргументы без имени программы; None — sys.argv[1:].

    Returns:
        Проверенный объект Config с абсолютными путями.

    Raises:
        SystemExit: при неверном порте или лимитах.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    config_file = Path(args.config).resolve() if args.config else DEFAULT_CONFIG_FILE
    values = read_config_file(config_file)
    config = Config(**values)

    overrides: dict[str, Any] = {}
    for key in ("host", "port", "db_path", "uploads_dir", "web_dir", "log_path",
                "max_upload", "log_level"):
        value = getattr(args, key)
        if value is None:
            continue
        if key in _PATH_FIELDS:
            overrides[key] = _to_path(value, PROJECT_ROOT)
        else:
            overrides[key] = value
    if overrides:
        config = replace(config, **overrides)

    if not 1 <= config.port <= 65535:
        raise SystemExit(f"Недопустимый порт: {config.port}")
    if config.max_upload <= 0 or config.max_upload > config.max_body:
        raise SystemExit("max_upload должен быть положительным и не больше max_body")
    config = replace(config, log_level=config.log_level.upper())
    if config.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise SystemExit(f"Неизвестный уровень журнала: {config.log_level}")
    return config


def describe(config: Config) -> str:
    """Короткая человекочитаемая сводка для журнала запуска.

    Args:
        config: Конфигурация.

    Returns:
        Строка с ключевыми параметрами.
    """
    return (
        f"host={config.host} port={config.port} "
        f"db={config.db_path} uploads={config.uploads_dir} "
        f"web={config.web_dir} max_upload={config.max_upload} "
        f"log_level={config.log_level}"
    )
