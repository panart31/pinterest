"""Журнал значимых действий пользователей.

События пишутся в формате ``event=login user=ksenia ip=127.0.0.1
result=ok``. Пароли и тексты сообщений не журналируются — только
идентификаторы и длина, чтобы не хранить личные данные в открытом виде.
"""

from __future__ import annotations

import logging

_audit_logger = logging.getLogger("mosaic.audit")


def _clean(value: object) -> str:
    """Приводит значение к строке без пробелов и переводов строк."""
    if value is None:
        return "-"
    return str(value).replace(" ", "_").replace("\n", "_").replace("\r", "_")


def audit_event(event: str, **fields: object) -> None:
    """Записывает одно событие аудита.

    Args:
        event: короткое имя события, например ``login`` или ``upload``.
        **fields: пары «поле — значение» (user, ip, post_id и т. п.).
    """
    parts = [f"event={_clean(event)}"]
    for key, value in fields.items():
        parts.append(f"{key}={_clean(value)}")
    _audit_logger.info(" ".join(parts))
