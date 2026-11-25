"""Сессии на cookie: создание, проверка и удаление.

Токен — случайная строка ``secrets.token_urlsafe(32)``; в базе хранится
только он, идентификатор пользователя и срок действия. Просроченные
сессии удаляются при обнаружении и при старте сервера.
"""

from __future__ import annotations

import secrets

from ..db.repository import Repository
from .clock import iso_in_days, parse_iso, to_iso, utc_now

COOKIE_NAME = "mosaic_session"


class SessionManager:
    """Выдаёт случайные токены и хранит их в таблице sessions.

    Attributes:
        repository: Репозиторий для работы с таблицей sessions.
        ttl_days: Срок жизни сессии в сутках.
        ttl_seconds: Тот же срок в секундах (для Max-Age cookie).
    """

    def __init__(self, repository: Repository, ttl_days: int = 7):
        """Создаёт менеджер сессий.

        Args:
            repository: Репозиторий приложения.
            ttl_days: Сколько суток живёт сессия.
        """
        self.repository = repository
        self.ttl_days = ttl_days
        self.ttl_seconds = ttl_days * 24 * 60 * 60

    def create(self, user_id: int) -> str:
        """Создаёт сессию и возвращает её токен.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Случайный токен для cookie.
        """
        token = secrets.token_urlsafe(32)
        self.repository.create_session(token, user_id, iso_in_days(self.ttl_days))
        return token

    def resolve(self, token: str | None) -> dict | None:
        """Возвращает пользователя по токену или None.

        Просроченные сессии удаляются сразу при обнаружении.

        Args:
            token: Значение cookie или None.

        Returns:
            Словарь ``id``, ``username``, ``display_name`` или None.
        """
        if not token:
            return None
        row = self.repository.get_session_user(token)
        if row is None:
            return None
        if parse_iso(row["expires_at"]) <= utc_now():
            self.repository.delete_session(token)
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
        }

    def destroy(self, token: str | None) -> None:
        """Удаляет сессию по токену.

        Args:
            token: Значение cookie или None (тогда ничего не делает).
        """
        if token:
            self.repository.delete_session(token)

    def purge_expired(self) -> int:
        """Удаляет все просроченные сессии (вызывается при старте).

        Returns:
            Количество удалённых записей.
        """
        return self.repository.purge_expired_sessions(to_iso(utc_now()))
