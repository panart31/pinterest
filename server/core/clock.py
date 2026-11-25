"""Единая точка получения времени.

Все метки времени хранятся в UTC в формате ISO 8601 с суффиксом ``Z``.
Клиент сам переводит их в местное время, поэтому сервер не зависит от
часового пояса и перехода на летнее время.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """Возвращает текущее время в UTC без микросекунд.

    Returns:
        Осведомлённый datetime с зоной UTC.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso(moment: datetime) -> str:
    """Преобразует момент времени в строку вида 2026-11-22T10:15:00Z.

    Args:
        moment: Время с любой зоной (будет приведено к UTC).

    Returns:
        Строка ISO 8601.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now() -> str:
    """Возвращает текущий момент в виде строки для SQLite.

    Returns:
        Строка ISO 8601 в UTC.
    """
    return to_iso(utc_now())


def iso_in_days(days: int) -> str:
    """Возвращает момент через ``days`` суток.

    Используется для срока жизни сессии.

    Args:
        days: Количество суток.

    Returns:
        Строка ISO 8601 в UTC.
    """
    return to_iso(utc_now() + timedelta(days=days))


def parse_iso(text: str) -> datetime:
    """Разбирает строку формата ``to_iso`` обратно в datetime (UTC).

    Args:
        text: Строка вида 2026-11-22T10:15:00Z.

    Returns:
        Осведомлённый datetime в UTC.

    Raises:
        ValueError: если строка не соответствует формату.
    """
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
