"""Настройка журналирования сервера.

Используются три именованных журнала:

* ``mosaic.access`` — одна строка на каждый HTTP-запрос в формате,
  близком к журналу Apache (без даты в начале: дата уже внутри строки);
* ``mosaic.server`` — запуск, остановка, ошибки и отладочные сведения;
* ``mosaic.audit`` — значимые действия пользователей: вход, регистрация,
  загрузка, удаление, комментарии и сообщения.

Все три пишут в консоль и в один файл ``server.log``. Форматтер
проверяет имя журнала: строки доступа остаются «чистыми», остальные
получают дату, уровень и имя журнала.
"""

from __future__ import annotations

import logging
import sys

from ..config import Config

ACCESS_LOGGER = "mosaic.access"
SERVER_LOGGER = "mosaic.server"
AUDIT_LOGGER = "mosaic.audit"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_handlers: list[logging.Handler] = []


class MosaicFormatter(logging.Formatter):
    """Форматтер с особым видом для строк доступа."""

    def format(self, record: logging.LogRecord) -> str:
        if record.name == ACCESS_LOGGER:
            return record.getMessage()
        return super().format(record)


def _build_handlers(config: Config) -> list[logging.Handler]:
    """Создаёт обработчики «консоль + файл» с общим форматтером."""
    formatter = MosaicFormatter(_LOG_FORMAT, _DATE_FORMAT)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(stream=sys.stderr)]
    try:
        handlers.append(
            logging.FileHandler(config.log_path, encoding="utf-8"))
    except OSError as exc:
        print(f"Предупреждение: не удалось открыть журнал "
              f"{config.log_path}: {exc}", file=sys.stderr)
    for handler in handlers:
        handler.setFormatter(formatter)
    return handlers


def setup_logging(config: Config) -> None:
    """Настраивает access/server/audit и очищает прежние обработчики.

    Вызывается один раз при старте, но безопасна и при повторном вызове
    (например, в тестах): старые файловые дескрипторы закрываются.
    """
    global _handlers
    for handler in _handlers:
        try:
            handler.close()
        except OSError:
            pass
    _handlers = _build_handlers(config)

    levels = {
        ACCESS_LOGGER: logging.INFO,
        SERVER_LOGGER: getattr(logging, config.log_level, logging.INFO),
        AUDIT_LOGGER: logging.INFO,
    }
    for name, level in levels.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        for old in list(logger.handlers):
            logger.removeHandler(old)
        for handler in _handlers:
            logger.addHandler(handler)


def close_logging() -> None:
    """Закрывает файловые обработчики (вызывается при остановке)."""
    global _handlers
    for handler in _handlers:
        try:
            handler.close()
        except OSError:
            pass
    _handlers = []
