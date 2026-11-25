"""Сборка и отправка HTTP-ответа.

Класс ``Response`` хранит код состояния, заголовки, тело и cookie,
а метод ``to_bytes`` сериализует их по правилам HTTP/1.1: стартовая
строка, Date, Server, пользовательские заголовки, Content-Length,
Connection: close и Set-Cookie.
"""

from __future__ import annotations

import json
import socket
from email.utils import formatdate
from typing import Any

STATUS_REASONS: dict[int, str] = {
    200: "OK",
    201: "Created",
    204: "No Content",
    302: "Found",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    500: "Internal Server Error",
}

SERVER_NAME = "Mosaic/1.0"


class Response:
    """HTTP-ответ: статус, заголовки, тело и cookie.

    Attributes:
        status: Код состояния (200, 201, 4xx, 5xx).
        body: Тело ответа в байтах.
        headers: Заголовки; Content-Type задаётся при создании.
    """

    def __init__(self, status: int = 200, body: bytes | str = b"",
                 content_type: str = "text/plain; charset=utf-8",
                 headers: dict[str, str] | None = None):
        """Создаёт ответ.

        Args:
            status: Код состояния.
            body: Тело; строка кодируется в UTF-8.
            content_type: Значение заголовка Content-Type.
            headers: Дополнительные заголовки.
        """
        self.status = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers: dict[str, str] = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self._cookies: list[str] = []

    # ------------------------------------------------------------ фабрики
    @classmethod
    def json(cls, data: Any, status: int = 200) -> "Response":
        """Создаёт JSON-ответ с кодировкой UTF-8.

        Args:
            data: Объект, сериализуемый в JSON.
            status: Код состояния.

        Returns:
            Ответ с Content-Type application/json.
        """
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return cls(status, payload, "application/json; charset=utf-8")

    @classmethod
    def html(cls, markup: str, status: int = 200) -> "Response":
        """Создаёт HTML-ответ.

        Args:
            markup: Разметка страницы.
            status: Код состояния.

        Returns:
            Ответ с Content-Type text/html.
        """
        return cls(status, markup, "text/html; charset=utf-8")

    @classmethod
    def text(cls, text: str, status: int = 200) -> "Response":
        """Создаёт текстовый ответ.

        Args:
            text: Текст ответа.
            status: Код состояния.

        Returns:
            Ответ с Content-Type text/plain.
        """
        return cls(status, text, "text/plain; charset=utf-8")

    @classmethod
    def error(cls, status: int, message: str,
              headers: dict[str, str] | None = None) -> "Response":
        """Создаёт ответ об ошибке в формате ``{"error": "..."}``.

        Args:
            status: Код ошибки.
            message: Текст, пригодный для показа пользователю.
            headers: Дополнительные заголовки (например, Allow).

        Returns:
            JSON-ответ с ошибкой.
        """
        response = cls.json({"error": message}, status)
        if headers:
            response.headers.update(headers)
        return response

    @classmethod
    def redirect(cls, location: str, status: int = 302) -> "Response":
        """Создаёт ответ-перенаправление.

        Args:
            location: Новый адрес.
            status: Код (302 по умолчанию).

        Returns:
            Ответ с заголовком Location.
        """
        response = cls(status, b"", "text/plain; charset=utf-8")
        response.headers["Location"] = location
        return response

    @classmethod
    def no_content(cls) -> "Response":
        """Создаёт ответ 204 без тела.

        Returns:
            Пустой ответ 204.
        """
        return cls(204, b"", "text/plain; charset=utf-8")

    @classmethod
    def binary(cls, data: bytes, content_type: str) -> "Response":
        """Создаёт ответ с бинарными данными (изображение, файл).

        Args:
            data: Содержимое файла.
            content_type: MIME-тип.

        Returns:
            Ответ 200 с указанным типом.
        """
        return cls(200, data, content_type)

    # ------------------------------------------------------------- cookie
    def set_cookie(self, name: str, value: str, *, max_age: int | None = None,
                   path: str = "/", http_only: bool = True,
                   same_site: str = "Lax") -> None:
        """Добавляет заголовок Set-Cookie.

        Args:
            name: Имя cookie.
            value: Значение (токен сессии).
            max_age: Срок жизни в секундах.
            path: Область видимости.
            http_only: Запретить доступ из JavaScript.
            same_site: Политика SameSite (Lax ослабляет CSRF).
        """
        parts = [f"{name}={value}", f"Path={path}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        if same_site:
            parts.append(f"SameSite={same_site}")
        self._cookies.append("; ".join(parts))

    def delete_cookie(self, name: str, path: str = "/") -> None:
        """Просит браузер удалить cookie.

        Args:
            name: Имя cookie.
            path: Область видимости.
        """
        self._cookies.append(
            f"{name}=; Path={path}; Max-Age=0; HttpOnly; SameSite=Lax")

    # ------------------------------------------------------------- отправка
    def to_bytes(self) -> bytes:
        """Сериализует ответ в байты по правилам HTTP/1.1.

        Returns:
            Заголовки и тело, готовые к отправке через сокет.
        """
        body = b"" if self.status in (204, 304) else self.body
        reason = STATUS_REASONS.get(self.status, "Unknown")
        lines = [f"HTTP/1.1 {self.status} {reason}"]
        lines.append(f"Date: {formatdate(usegmt=True)}")
        lines.append(f"Server: {SERVER_NAME}")
        for name, value in self.headers.items():
            lines.append(f"{name}: {value}")
        if self.status not in (204, 304):
            lines.append(f"Content-Length: {len(body)}")
        lines.append("Connection: close")
        for cookie in self._cookies:
            lines.append(f"Set-Cookie: {cookie}")
        head = "\r\n".join(lines) + "\r\n\r\n"
        return head.encode("iso-8859-1") + body

    def send(self, conn: socket.socket) -> int:
        """Отправляет ответ через сокет.

        Args:
            conn: Соединение с клиентом.

        Returns:
            Размер тела в байтах (для журнала доступа).
        """
        conn.sendall(self.to_bytes())
        return len(self.body)

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<Response {self.status} {len(self.body)} bytes>"
