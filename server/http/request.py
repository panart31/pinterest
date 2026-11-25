"""Разбор HTTP-запроса, пришедшего по TCP-сокету.

Реализовано подмножество HTTP/1.1 (RFC 9112), достаточное для приложения:
строка запроса, заголовки, тело по Content-Length, query string и cookie.
Chunked-кодировка сознательно не поддерживается — клиент всегда знает
размер тела заранее (JSON или multipart).

Чтение идёт порциями: TCP не сохраняет границы сообщений, поэтому парсер
накапливает буфер и ищет конец заголовков по последовательности CRLF CRLF,
а конец тела определяет по Content-Length.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any

# Символы, допустимые в имени метода и в имени заголовка (RFC 9110, token).
_TOKEN_CHARS = frozenset(
    "!#$%&'*+-.^_`|~0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_SUPPORTED_VERSIONS = ("HTTP/1.1", "HTTP/1.0")


class HTTPError(Exception):
    """Ошибка протокола, которую нужно превратить в HTTP-ответ.

    Attributes:
        status: Код состояния для ответа.
        message: Текст, пригодный для показа клиенту.
    """

    def __init__(self, status: int, message: str):
        """Создаёт ошибку с кодом и текстом.

        Args:
            status: Код состояния (400, 401, 404, 413 и т. п.).
            message: Пояснение для клиента.
        """
        super().__init__(message)
        self.status = status
        self.message = message


def percent_decode(text: str) -> str:
    """Раскодирует %XX последовательности в UTF-8.

    Некорректные последовательности остаются как есть — так же
    поступают распространённые веб-серверы.

    Args:
        text: Строка из пути или query string.

    Returns:
        Декодированная строка UTF-8.
    """
    if "%" not in text:
        return text
    result = bytearray()
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%" and index + 3 <= len(text):
            pair = text[index + 1:index + 3]
            try:
                result.append(int(pair, 16))
            except ValueError:
                result.extend(char.encode("utf-8"))
                index += 1
                continue
            index += 3
            continue
        result.extend(char.encode("utf-8"))
        index += 1
    return result.decode("utf-8", errors="replace")


def parse_query_string(raw: str) -> dict[str, list[str]]:
    """Разбирает query string в словарь списков значений.

    Args:
        raw: Строка после знака ``?`` (без него).

    Returns:
        Словарь: ключ → список значений (повторяющиеся ключи сохраняются).
    """
    query: dict[str, list[str]] = {}
    if not raw:
        return query
    for pair in raw.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key = percent_decode(key.replace("+", " "))
        value = percent_decode(value.replace("+", " "))
        query.setdefault(key, []).append(value)
    return query


def parse_cookies(header_value: str) -> dict[str, str]:
    """Разбирает заголовок Cookie.

    Args:
        header_value: Значение вида ``name=value; name2=value2``.

    Returns:
        Словарь cookie (последнее значение побеждает).
    """
    cookies: dict[str, str] = {}
    for chunk in header_value.split(";"):
        name, sep, value = chunk.strip().partition("=")
        if sep and name:
            cookies[name] = value
    return cookies


def _is_token(text: str) -> bool:
    """Проверяет, состоит ли строка только из допустимых символов token.

    Args:
        text: Имя метода или заголовка.

    Returns:
        True, если строка непустая и все символы допустимы.
    """
    return bool(text) and all(char in _TOKEN_CHARS for char in text)


@dataclass
class Request:
    """Разобранный HTTP-запрос.

    Attributes:
        method: Метод (GET, POST).
        target: Исходная цель запроса вместе с query string.
        version: Версия протокола, например ``HTTP/1.1``.
        headers: Заголовки с именами в нижнем регистре.
        body: Тело запроса (пустое, если его нет).
        path: Путь без query string, после percent-декодирования.
        query: Параметры query string; у каждого может быть несколько
            значений.
        remote_addr: IP-адрес клиента (заполняет TCP-сервер).
        request_id: Короткий идентификатор запроса для журнала.
        user: Пользователь сессии или None (заполняет Application).
    """

    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: bytes = b""
    path: str = "/"
    query: dict[str, list[str]] = field(default_factory=dict)
    remote_addr: str = ""
    request_id: str = ""
    user: dict[str, Any] | None = None

    def header(self, name: str, default: str | None = None) -> str | None:
        """Возвращает значение заголовка без учёта регистра.

        Args:
            name: Имя заголовка в любом регистре.
            default: Значение, если заголовка нет.

        Returns:
            Значение или default.
        """
        return self.headers.get(name.lower(), default)

    @property
    def content_type(self) -> str:
        """Значение заголовка Content-Type (пустая строка, если нет)."""
        return self.header("content-type", "") or ""

    @property
    def cookies(self) -> dict[str, str]:
        """Разобранный заголовок Cookie."""
        return parse_cookies(self.header("cookie", "") or "")

    def query_one(self, name: str, default: str | None = None) -> str | None:
        """Возвращает первое значение параметра query string.

        Args:
            name: Имя параметра.
            default: Значение, если параметра нет.

        Returns:
            Первое значение или default.
        """
        values = self.query.get(name)
        return values[0] if values else default

    def json_body(self) -> dict[str, Any]:
        """Разбирает тело как JSON-объект.

        Returns:
            Словарь из тела запроса.

        Raises:
            HTTPError: 400, если тело пустое или это не JSON-объект.
        """
        if not self.body:
            raise HTTPError(400, "Тело запроса пусто")
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPError(400, "Тело запроса не является корректным JSON")
        if not isinstance(data, dict):
            raise HTTPError(400, "JSON должен быть объектом")
        return data

    def form_body(self) -> dict[str, str]:
        """Разбирает тело application/x-www-form-urlencoded.

        Returns:
            Словарь полей (первое значение для повторяющихся ключей).

        Raises:
            HTTPError: 400, если тело не в UTF-8.
        """
        try:
            text = self.body.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPError(400, "Тело формы должно быть в UTF-8")
        result: dict[str, str] = {}
        for key, values in parse_query_string(text).items():
            result[key] = values[0]
        return result


def parse_request_line(line: str) -> tuple[str, str, str]:
    """Разбирает строку вида ``GET /api/feed HTTP/1.1``.

    Args:
        line: Первая строка запроса.

    Returns:
        Кортеж (метод, цель, версия).

    Raises:
        HTTPError: 400 при неверном числе частей, методе, версии или
            цели, не начинающейся с ``/``.
    """
    parts = line.split(" ")
    if len(parts) != 3:
        raise HTTPError(400, "Некорректная строка запроса")
    method, target, version = parts
    if not _is_token(method):
        raise HTTPError(400, "Некорректный метод запроса")
    if version not in _SUPPORTED_VERSIONS:
        raise HTTPError(400, "Поддерживается только HTTP/1.0 и HTTP/1.1")
    if not target.startswith("/"):
        raise HTTPError(400, "Цель запроса должна начинаться с «/»")
    return method, target, version


def parse_header_lines(lines: list[str]) -> dict[str, str]:
    """Разбирает блок заголовков в словарь с ключами в нижнем регистре.

    Args:
        lines: Строки между стартовой строкой и пустой строкой.

    Returns:
        Словарь заголовков.

    Raises:
        HTTPError: 400 при пустой строке, переносе, отсутствии
            двоеточия, неверном имени или дублирующемся Content-Length.
    """
    headers: dict[str, str] = {}
    for line in lines:
        if not line:
            raise HTTPError(400, "Пустая строка внутри заголовков")
        if line[0] in " \t":
            raise HTTPError(400, "Перенос строки в заголовке запрещён")
        name, sep, value = line.partition(":")
        if not sep:
            raise HTTPError(400, "Заголовок без двоеточия")
        if not _is_token(name):
            raise HTTPError(400, "Некорректное имя заголовка")
        key = name.lower()
        if key == "content-length" and key in headers:
            raise HTTPError(400, "Дублирующийся Content-Length")
        headers[key] = value.strip()
    return headers


def _read_head(conn: socket.socket, max_header: int) -> tuple[bytes, bytes]:
    """Читает данные до пустой строки.

    Args:
        conn: Соединение с клиентом.
        max_header: Предельный размер блока заголовков.

    Returns:
        Пару (байты заголовков без CRLF CRLF, остаток буфера).

    Raises:
        HTTPError: 400 при превышении лимита, пустом запросе или
            обрыве соединения до конца заголовков.
    """
    buffer = b""
    while True:
        separator = buffer.find(b"\r\n\r\n")
        if separator >= 0:
            if separator + 4 > max_header:
                raise HTTPError(400, "Слишком большой блок заголовков")
            return buffer[:separator], buffer[separator + 4:]
        if len(buffer) > max_header:
            raise HTTPError(400, "Слишком большой блок заголовков")
        chunk = conn.recv(4096)
        if not chunk:
            if not buffer:
                raise HTTPError(400, "Пустой запрос")
            raise HTTPError(400, "Соединение закрыто до конца заголовков")
        buffer += chunk


def _read_body(conn: socket.socket, already_read: bytes, length: int) -> bytes:
    """Дочитывает тело запроса ровно до Content-Length байт.

    Args:
        conn: Соединение с клиентом.
        already_read: Байты, уже попавшие в буфер вместе с заголовками.
        length: Требуемая длина тела.

    Returns:
        Тело запроса.

    Raises:
        HTTPError: 400, если соединение закрылось раньше.
    """
    body = already_read[:length]
    while len(body) < length:
        chunk = conn.recv(min(65536, length - len(body)))
        if not chunk:
            raise HTTPError(400, "Тело запроса короче Content-Length")
        body += chunk
    return body


def read_request(conn: socket.socket, max_header: int = 16 * 1024,
                 max_body: int = 6 * 1024 * 1024) -> Request:
    """Полностью читает и разбирает один запрос из соединения.

    Args:
        conn: Соединение с клиентом.
        max_header: Предельный размер заголовков.
        max_body: Предельный размер тела.

    Returns:
        Объект Request с методом, путём, заголовками, телом и query.

    Raises:
        HTTPError: 400 при синтаксической ошибке, отсутствии Host,
            неподдерживаемом Transfer-Encoding или неверном
            Content-Length; 413 при слишком большом теле.
    """
    head_bytes, rest = _read_head(conn, max_header)
    try:
        head = head_bytes.decode("iso-8859-1")
    except UnicodeDecodeError:  # pragma: no cover - latin-1 не падает никогда
        raise HTTPError(400, "Некорректная кодировка заголовков")

    head_lines = head.split("\r\n")
    if not head_lines or not head_lines[0]:
        raise HTTPError(400, "Пустая строка запроса")

    method, target, version = parse_request_line(head_lines[0])
    headers = parse_header_lines(head_lines[1:])

    # HTTP/1.1 требует заголовок Host (RFC 9112, раздел 3.2).
    if version == "HTTP/1.1" and "host" not in headers:
        raise HTTPError(400, "Отсутствует обязательный заголовок Host")

    if "transfer-encoding" in headers:
        raise HTTPError(400, "Transfer-Encoding не поддерживается")

    length = 0
    raw_length = headers.get("content-length")
    if raw_length is not None:
        if not raw_length.isdigit():
            raise HTTPError(400, "Content-Length должен быть числом")
        length = int(raw_length)
        if length > max_body:
            raise HTTPError(413, "Тело запроса слишком велико")

    body = _read_body(conn, rest, length) if length else b""
    path, _, raw_query = target.partition("?")
    if "\x00" in path:
        raise HTTPError(400, "Недопустимый символ в пути")
    return Request(
        method=method,
        target=target,
        version=version,
        headers=headers,
        body=body,
        path=percent_decode(path),
        query=parse_query_string(raw_query),
    )
