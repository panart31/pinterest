"""Вспомогательные средства тестов: запуск сервера и «сырой» клиент.

Клиент работает через настоящий TCP-сокет и вручную собирает запрос,
как это делал бы браузер. Никаких HTTP-библиотек.
"""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.app import Application
from server.config import PROJECT_ROOT, Config
from server.core.server import HTTPServer


@dataclass
class TestResponse:
    """Разобранный HTTP-ответ."""

    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name: str) -> str | None:
        name = name.lower()
        for key, value in self.headers:
            if key.lower() == name:
                return value
        return None

    def all_headers(self, name: str) -> list[str]:
        name = name.lower()
        return [value for key, value in self.headers
                if key.lower() == name]

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def parse_response(raw: bytes) -> TestResponse:
    """Разбирает ответ HTTP/1.1, сохраняя повторяющиеся заголовки."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        raise AssertionError(f"Не HTTP-ответ: {raw[:120]!r}")
    status = int(lines[0].split(" ")[1])
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers.append((name.strip(), value.strip()))
    length_header = next((v for k, v in headers
                          if k.lower() == "content-length"), None)
    length = int(length_header) if length_header else len(body)
    return TestResponse(status, headers, body[:length])


class TestClient:
    """Небольшой HTTP-клиент на сокетах с поддержкой cookie."""

    __test__ = False  # pytest не должен собирать этот класс как тест

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str,
                headers: dict[str, str] | None = None,
                body: bytes = b"") -> TestResponse:
        lines = [f"{method} {path} HTTP/1.1", f"Host: {self.host}:{self.port}"]
        for name, value in (headers or {}).items():
            lines.append(f"{name}: {value}")
        if self.cookies:
            lines.append("Cookie: " + "; ".join(
                f"{name}={value}" for name, value in self.cookies.items()))
        if body:
            lines.append(f"Content-Length: {len(body)}")
        lines.append("Connection: close")
        raw_request = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body

        with socket.create_connection((self.host, self.port),
                                      timeout=self.timeout) as sock:
            sock.sendall(raw_request)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        response = parse_response(b"".join(chunks))
        self._store_cookies(response)
        return response

    def _store_cookies(self, response: TestResponse) -> None:
        for raw in response.all_headers("Set-Cookie"):
            name, _, rest = raw.partition("=")
            value = rest.split(";")[0]
            if "Max-Age=0" in raw:
                self.cookies.pop(name.strip(), None)
            else:
                self.cookies[name.strip()] = value

    # --------------------------------------------------------- сокращения
    def get(self, path: str) -> TestResponse:
        return self.request("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> TestResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request("POST", path, {
            "Content-Type": "application/json; charset=utf-8"}, body)

    def post_form(self, path: str, payload: dict[str, str]) -> TestResponse:
        from urllib.parse import urlencode  # только для кодирования формы
        body = urlencode(payload).encode("utf-8")
        return self.request("POST", path, {
            "Content-Type": "application/x-www-form-urlencoded"}, body)

    def post_multipart(self, path: str, filename: str, data: bytes,
                       fields: dict[str, str] | None = None,
                       boundary: str = "----MosaicTestBoundary",
                       extra_headers: dict[str, str] | None = None,
                       ) -> TestResponse:
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        if filename:
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"image\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
            chunks.append(data)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        headers = {"Content-Type":
                   f"multipart/form-data; boundary={boundary}"}
        if extra_headers:
            headers.update(extra_headers)
        return self.request("POST", path, headers, body)


def make_config(tmp_path: Path, **overrides: Any) -> Config:
    """Конфигурация для тестов: отдельная БД, малые лимиты."""
    defaults: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 0,
        "db_path": tmp_path / "test.db",
        "uploads_dir": tmp_path / "uploads",
        "web_dir": PROJECT_ROOT / "web",
        "log_path": tmp_path / "server.log",
        "max_upload": 64 * 1024,
        "max_body": 128 * 1024,
        "timeout": 5.0,
    }
    defaults.update(overrides)
    return Config(**defaults).ensure_dirs()


class ServerFixture:
    """Запущенный сервер вместе с фабрикой клиентов."""

    def __init__(self, config: Config):
        self.config = config
        self.app = Application(config)
        self.server = HTTPServer(config, self.app)
        self.thread: threading.Thread | None = None

    def start(self) -> "ServerFixture":
        self.server.port = self.config.port
        self.server.start()
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        return self

    def client(self) -> TestClient:
        return TestClient("127.0.0.1", self.server.port)

    def stop(self) -> None:
        self.server.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.app.close()


def register(client: TestClient, username: str = "ksenia",
             password: str = "secret123",
             display_name: str = "Ксения") -> TestResponse:
    return client.post_json("/api/register", {
        "username": username,
        "password": password,
        "display_name": display_name,
    })


def login(client: TestClient, username: str = "ksenia",
          password: str = "secret123") -> TestResponse:
    return client.post_json("/api/login", {
        "username": username, "password": password})


def new_user(client: TestClient, username: str, password: str = "secret123",
             display_name: str | None = None) -> TestClient:
    """Регистрирует и входит; возвращает клиент с cookie."""
    register(client, username, password, display_name or username)
    response = login(client, username, password)
    assert response.status == 200, response.text()
    return client


# Минимальный корректный PNG 1x1 (прозрачный пиксель).
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
    "426082"
)

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01"
JPEG_BYTES += b"\x00" * 40 + b"\xff\xd9"


@dataclass
class SeededUser:
    client: TestClient
    user: dict[str, Any]
    posts: list[dict[str, Any]] = field(default_factory=list)
