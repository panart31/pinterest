"""Слой доступа к данным: только параметризованные SQL-запросы.

Репозиторий ничего не знает об HTTP и сессиях: он принимает простые
значения и возвращает словари. Все запросы параметризованы, поэтому
SQL-инъекция через пользовательские строки невозможна. Поиск по
кириллице выполняется через зарегистрированную функцию ``py_lower``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .database import Database

UserRow = dict[str, Any]


def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Превращает sqlite3.Row в обычный словарь.

    Args:
        row: Строка результата или None.

    Returns:
        Словарь или None.
    """
    return dict(row) if row is not None else None


def _like_pattern(text: str) -> str:
    """Экранирует спецсимволы LIKE и оборачивает строку в проценты.

    Args:
        text: Пользовательская строка (уже в нижнем регистре).

    Returns:
        Шаблон для ``LIKE ... ESCAPE '\\'``.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class Repository:
    """Все SQL-запросы приложения собраны здесь.

    Attributes:
        db: Обёртка Database с соединением на поток.
    """

    def __init__(self, db: Database):
        """Сохраняет ссылку на базу.

        Args:
            db: Обёртка подключения к SQLite.
        """
        self.db = db

    # ------------------------------------------------------------------ users
    def create_user(self, username: str, display_name: str, salt: str,
                    password_hash: str, created_at: str) -> dict[str, Any]:
        """Создаёт пользователя.

        Args:
            username: Логин (уникальный, без учёта регистра).
            display_name: Отображаемое имя.
            salt: Соль в hex-виде.
            password_hash: PBKDF2-хеш в hex-виде.
            created_at: Время создания в ISO 8601.

        Returns:
            Словарь ``id``, ``username``, ``display_name``.

        Raises:
            sqlite3.IntegrityError: если логин уже занят.
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, display_name, password_hash, salt, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (username, display_name, password_hash, salt, created_at),
            )
            user_id = int(cursor.lastrowid)
        return {"id": user_id, "username": username, "display_name": display_name}

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Возвращает пользователя вместе с хешем и солью (для входа).

        Args:
            username: Логин без учёта регистра.

        Returns:
            Строка пользователя или None.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, password_hash, salt, created_at "
                "FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return _as_dict(row)

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        """Возвращает публичные данные пользователя по id.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Словарь или None.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return _as_dict(row)

    def search_users(self, query: str, exclude_id: int,
                     limit: int = 10) -> list[dict[str, Any]]:
        """Ищет людей по логину и имени без учёта регистра.

        Args:
            query: Строка поиска.
            exclude_id: id текущего пользователя (исключается из выдачи).
            limit: Максимальное число результатов.

        Returns:
            Список пользователей; совпадения по логину идут первыми.
        """
        pattern = _like_pattern(query.lower())
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id, username, display_name FROM users "
                "WHERE id != ? AND (py_lower(username) LIKE ? ESCAPE '\\' "
                "OR py_lower(display_name) LIKE ? ESCAPE '\\') "
                "ORDER BY (py_lower(username) LIKE ? ESCAPE '\\') DESC, "
                "         username LIMIT ?",
                (exclude_id, pattern, pattern, pattern, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- sessions
    def create_session(self, token: str, user_id: int, expires_at: str) -> None:
        """Сохраняет сессию.

        Args:
            token: Случайный токен.
            user_id: Владелец сессии.
            expires_at: Срок действия в ISO 8601.
        """
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires_at),
            )

    def get_session_user(self, token: str) -> dict[str, Any] | None:
        """Возвращает пользователя и срок действия сессии одним запросом.

        Args:
            token: Токен из cookie.

        Returns:
            Словарь с ``expires_at`` и полями пользователя или None.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT s.expires_at, u.id, u.username, u.display_name "
                "FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token = ?",
                (token,),
            ).fetchone()
        return _as_dict(row)

    def delete_session(self, token: str) -> None:
        """Удаляет сессию (выход из системы).

        Args:
            token: Токен из cookie.
        """
        with self.db.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def purge_expired_sessions(self, now_iso: str) -> int:
        """Удаляет все сессии с истёкшим сроком.

        Args:
            now_iso: Текущее время в ISO 8601.

        Returns:
            Количество удалённых записей.
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (now_iso,))
            return cursor.rowcount

    # ------------------------------------------------------------------ posts
    _POST_SELECT = (
        "SELECT p.id, p.caption, p.filename, p.created_at, "
        "       u.id AS author_id, u.username AS author_username, "
        "       u.display_name AS author_display_name, "
        "       (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS likes, "
        "       (SELECT COUNT(*) FROM comments c "
        "         WHERE c.post_id = p.id) AS comments, "
        "       EXISTS(SELECT 1 FROM likes l2 "
        "              WHERE l2.post_id = p.id AND l2.user_id = ?) AS liked "
        "FROM posts p JOIN users u ON u.id = p.user_id "
    )

    def create_post(self, user_id: int, filename: str, caption: str,
                    created_at: str) -> int:
        """Создаёт публикацию.

        Args:
            user_id: Автор.
            filename: Имя файла в хранилище.
            caption: Подпись (может быть пустой).
            created_at: Время создания в ISO 8601.

        Returns:
            Идентификатор новой публикации.
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO posts (user_id, filename, caption, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, filename, caption, created_at),
            )
            return int(cursor.lastrowid)

    def get_post(self, post_id: int, viewer_id: int) -> dict[str, Any] | None:
        """Возвращает полную карточку публикации.

        Args:
            post_id: Идентификатор публикации.
            viewer_id: Кто смотрит (для поля liked).

        Returns:
            Словарь с автором, лайками и комментариями или None.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                self._POST_SELECT + "WHERE p.id = ?", (viewer_id, post_id)
            ).fetchone()
        return _as_dict(row)

    def list_posts(self, viewer_id: int, limit: int, offset: int,
                   author_id: int | None = None) -> list[dict[str, Any]]:
        """Возвращает страницу ленты.

        Args:
            viewer_id: Кто смотрит (для поля liked).
            limit: Размер страницы.
            offset: Смещение.
            author_id: Если задан — только публикации этого автора.

        Returns:
            Список карточек в порядке убывания id.
        """
        sql = self._POST_SELECT
        params: list[Any] = [viewer_id]
        if author_id is not None:
            sql += "WHERE p.user_id = ? "
            params.append(author_id)
        sql += "ORDER BY p.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def search_posts(self, query: str, viewer_id: int,
                     limit: int = 10) -> list[dict[str, Any]]:
        """Ищет публикации по подписи (без учёта регистра).

        Args:
            query: Строка поиска.
            viewer_id: Кто смотрит (для поля liked).
            limit: Максимальное число результатов.

        Returns:
            Список карточек, новые сверху.
        """
        pattern = _like_pattern(query.lower())
        with self.db.connection() as conn:
            rows = conn.execute(
                self._POST_SELECT +
                "WHERE py_lower(p.caption) LIKE ? ESCAPE '\\' "
                "ORDER BY p.id DESC LIMIT ?",
                (viewer_id, pattern, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_posts(self, author_id: int | None = None) -> int:
        """Считает публикации (все или конкретного автора).

        Args:
            author_id: Автор или None для общей ленты.

        Returns:
            Количество публикаций.
        """
        with self.db.connection() as conn:
            if author_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM posts WHERE user_id = ?",
                    (author_id,)).fetchone()
        return int(row["n"])

    def delete_post(self, post_id: int, user_id: int) -> str | None:
        """Удаляет публикацию владельца.

        Args:
            post_id: Идентификатор публикации.
            user_id: Требуемый автор.

        Returns:
            Имя файла для удаления с диска или None, если публикация
            не найдена или принадлежит другому пользователю.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT filename FROM posts WHERE id = ? AND user_id = ?",
                (post_id, user_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        return str(row["filename"])

    # ------------------------------------------------------------------ likes
    def toggle_like(self, post_id: int, user_id: int) -> tuple[bool, int] | None:
        """Ставит или снимает лайк в одной транзакции.

        Args:
            post_id: Публикация.
            user_id: Пользователь.

        Returns:
            Пару «лайк теперь стоит, общее число лайков» или None, если
            публикации нет.
        """
        conn = self.db.connection()
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
            if exists is None:
                return None
            liked_row = conn.execute(
                "SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?",
                (post_id, user_id),
            ).fetchone()
            if liked_row is None:
                conn.execute(
                    "INSERT OR IGNORE INTO likes (post_id, user_id) VALUES (?, ?)",
                    (post_id, user_id),
                )
                liked = True
            else:
                conn.execute(
                    "DELETE FROM likes WHERE post_id = ? AND user_id = ?",
                    (post_id, user_id),
                )
                liked = False
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM likes WHERE post_id = ?", (post_id,)
            ).fetchone()["n"]
        return liked, int(total)

    # --------------------------------------------------------------- comments
    def create_comment(self, post_id: int, user_id: int, text: str,
                       created_at: str) -> dict[str, Any] | None:
        """Добавляет комментарий.

        Args:
            post_id: Публикация.
            user_id: Автор комментария.
            text: Текст (уже провалидированный).
            created_at: Время в ISO 8601.

        Returns:
            Словарь комментария или None, если публикации нет.
        """
        conn = self.db.connection()
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
            if exists is None:
                return None
            cursor = conn.execute(
                "INSERT INTO comments (post_id, user_id, text, created_at) "
                "VALUES (?, ?, ?, ?)",
                (post_id, user_id, text, created_at),
            )
            comment_id = int(cursor.lastrowid)
        return {"id": comment_id, "post_id": post_id, "user_id": user_id,
                "text": text, "created_at": created_at}

    def list_comments(self, post_id: int, limit: int = 200) -> list[dict[str, Any]]:
        """Возвращает комментарии публикации в хронологическом порядке.

        Args:
            post_id: Публикация.
            limit: Максимальное число комментариев.

        Returns:
            Список комментариев с данными автора.
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT c.id, c.text, c.created_at, u.id AS author_id, "
                "       u.username, u.display_name "
                "FROM comments c JOIN users u ON u.id = c.user_id "
                "WHERE c.post_id = ? ORDER BY c.id ASC LIMIT ?",
                (post_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------- messages
    def create_message(self, sender_id: int, recipient_id: int, text: str,
                       created_at: str) -> dict[str, Any]:
        """Сохраняет личное сообщение.

        Args:
            sender_id: Отправитель.
            recipient_id: Получатель.
            text: Текст сообщения.
            created_at: Время в ISO 8601.

        Returns:
            Словарь созданного сообщения (is_read = 0).
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (sender_id, recipient_id, text, created_at, "
                "is_read) VALUES (?, ?, ?, ?, 0)",
                (sender_id, recipient_id, text, created_at),
            )
            message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "text": text,
            "created_at": created_at,
            "is_read": 0,
        }

    def list_dialog(self, user_id: int, other_id: int, after_id: int = 0,
                    limit: int = 200) -> list[dict[str, Any]]:
        """Возвращает сообщения между двумя пользователями.

        Args:
            user_id: Текущий пользователь.
            other_id: Собеседник.
            after_id: Вернуть только сообщения с id больше этого.
            limit: Максимальное число сообщений.

        Returns:
            Сообщения в хронологическом порядке с логином отправителя.
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT m.id, m.sender_id, m.recipient_id, m.text, m.created_at, "
                "       m.is_read, u.username AS sender_username, "
                "       u.display_name AS sender_display_name "
                "FROM messages m JOIN users u ON u.id = m.sender_id "
                "WHERE ((m.sender_id = ? AND m.recipient_id = ?) "
                "    OR (m.sender_id = ? AND m.recipient_id = ?)) "
                "  AND m.id > ? "
                "ORDER BY m.id ASC LIMIT ?",
                (user_id, other_id, other_id, user_id, after_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_dialogs(self, user_id: int) -> list[dict[str, Any]]:
        """Возвращает список собеседников с последним сообщением.

        Args:
            user_id: Текущий пользователь.

        Returns:
            Список диалогов: пользователь, последний текст и время,
            число непрочитанных.
        """
        sql = """
        WITH peers AS (
            SELECT CASE WHEN sender_id = ? THEN recipient_id ELSE sender_id END
                       AS peer_id,
                   MAX(id) AS last_id
            FROM messages
            WHERE sender_id = ? OR recipient_id = ?
            GROUP BY peer_id
        )
        SELECT u.id AS user_id, u.username, u.display_name,
               m.text AS last_text, m.created_at AS last_at,
               m.sender_id AS last_sender_id,
               (SELECT COUNT(*) FROM messages x
                 WHERE x.sender_id = u.id AND x.recipient_id = ?
                   AND x.is_read = 0) AS unread
        FROM peers p
        JOIN messages m ON m.id = p.last_id
        JOIN users u ON u.id = p.peer_id
        ORDER BY m.id DESC
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql, (user_id, user_id, user_id, user_id)).fetchall()
        return [dict(row) for row in rows]

    def mark_read(self, reader_id: int, other_id: int) -> int:
        """Помечает прочитанными сообщения от собеседника.

        Args:
            reader_id: Кто читает.
            other_id: От кого пришли сообщения.

        Returns:
            Число обновлённых сообщений.
        """
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE messages SET is_read = 1 "
                "WHERE recipient_id = ? AND sender_id = ? AND is_read = 0",
                (reader_id, other_id),
            )
            return cursor.rowcount

    def unread_total(self, user_id: int) -> int:
        """Считает все непрочитанные сообщения пользователя.

        Args:
            user_id: Пользователь.

        Returns:
            Количество непрочитанных.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM messages "
                "WHERE recipient_id = ? AND is_read = 0",
                (user_id,),
            ).fetchone()
        return int(row["n"])
