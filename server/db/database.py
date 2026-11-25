"""Работа с SQLite: подключение на поток, схема, транзакции.

Соединение с SQLite нельзя безопасно использовать из нескольких потоков,
поэтому каждому потоку выдаётся собственное соединение
(thread-local). Это стандартный приём для модели «поток на соединение».

При подключении включаются WAL (параллельные чтения), внешние ключи и
функция ``py_lower`` — юникодный аналог ``lower()``, потому что встроенные
LIKE и COLLATE NOCASE в SQLite понимают только латиницу.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name  TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  salt          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename   TEXT NOT NULL,
  caption    TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS likes (
  post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  sender_id    INTEGER NOT NULL REFERENCES users(id),
  recipient_id INTEGER NOT NULL REFERENCES users(id),
  text         TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  is_read      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comments (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_created   ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_dialog ON messages(sender_id, recipient_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_inbox  ON messages(recipient_id, is_read);
CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_comments_post   ON comments(post_id, id);
"""


def _py_lower(value: object) -> str:
    """Юникодный ``lower()`` для SQLite.

    Встроенные LIKE и COLLATE NOCASE в SQLite понимают только латиницу,
    поэтому для поиска по кириллице регистрируем собственную функцию.

    Args:
        value: Значение из базы.

    Returns:
        Строка в нижнем регистре.
    """
    return str(value).lower() if value is not None else ""


class Database:
    """Обёртка над sqlite3 с ленивым соединением на каждый поток.

    Attributes:
        path: Путь к файлу базы данных.
    """

    def __init__(self, path: Path):
        """Запоминает путь и создаёт структуры для thread-local соединений.

        Args:
            path: Путь к файлу ``.db`` (каталог создаётся отдельно).
        """
        self.path = Path(path)
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._guard = threading.Lock()

    def connection(self) -> sqlite3.Connection:
        """Возвращает соединение, привязанное к текущему потоку.

        При первом обращении создаёт соединение, включает WAL,
        внешние ключи, busy_timeout и регистрирует ``py_lower``.

        Returns:
            Соединение sqlite3 с Row-фабрикой.
        """
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.create_function("py_lower", 1, _py_lower, deterministic=True)
            self._local.connection = conn
            with self._guard:
                self._all_connections.append(conn)
        return conn

    def init_schema(self) -> None:
        """Создаёт таблицы и индексы, если их ещё нет.

        Выполняется при старте приложения; ``IF NOT EXISTS`` делает
        операцию безопасной для существующей базы.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connection()
        conn.executescript(SCHEMA)
        conn.commit()

    def close(self) -> None:
        """Закрывает все открытые соединения.

        Вызывается при остановке сервера; ошибки отдельных соединений
        игнорируются, чтобы закрыть остальные.
        """
        with self._guard:
            connections = list(self._all_connections)
            self._all_connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()
