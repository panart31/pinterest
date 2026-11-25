#!/usr/bin/env python3
"""Консольный HTTP-клиент на голых сокетах.

Доказывает, что клиентская сторона тоже умеет работать с протоколом
без библиотек: запрос собирается вручную, ответ разбирается вручную.
Используется для демонстрации и в интеграционных тестах.

Примеры:
    python client_raw/raw_client.py --host 127.0.0.1 --port 8000 register
    python client_raw/raw_client.py login ksenia secret123
    python client_raw/raw_client.py feed
    python client_raw/raw_client.py send artem "Привет!"
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.parse
from pathlib import Path
from typing import Any

STATUS_REASONS = {200: "OK", 201: "Created", 204: "No Content"}
COOKIE_FILE = Path(__file__).resolve().parent / ".session"


class RawResponse:
    """Ответ сервера, разобранный вручную."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def encode_request(method: str, path: str, host: str, port: int,
                   headers: dict[str, str] | None = None,
                   body: bytes = b"") -> bytes:
    """Собирает HTTP-запрос вручную, байт за байтом."""
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}:{port}"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    if body:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: close")
    head = "\r\n".join(lines) + "\r\n\r\n"
    return head.encode("utf-8") + body


def read_response(sock: socket.socket) -> RawResponse:
    """Читает ответ до закрытия соединения и разбирает его."""
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    if not lines or not lines[0].startswith("HTTP/"):
        raise RuntimeError("Сервер вернул не HTTP-ответ")
    status = int(lines[0].split(" ")[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or 0)
    return RawResponse(status, headers, body[:length] if length else b"")


class RawClient:
    """Минимальный клиент: соединение, запрос, ответ, закрытие."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000,
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str,
                headers: dict[str, str] | None = None,
                body: bytes = b"") -> RawResponse:
        all_headers = dict(headers or {})
        if self.cookies:
            all_headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self.cookies.items())
        request = encode_request(method, path, self.host, self.port,
                                 all_headers, body)
        with socket.create_connection((self.host, self.port),
                                      timeout=self.timeout) as sock:
            sock.sendall(request)
            response = read_response(sock)
        for cookie in self._set_cookies(response):
            name, _, value = cookie.split(";")[0].partition("=")
            if "Max-Age=0" in cookie:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response

    @staticmethod
    def _set_cookies(response: RawResponse) -> list[str]:
        raw = response.headers.get("set-cookie", "")
        return [raw] if raw else []

    def get(self, path: str) -> RawResponse:
        return self.request("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> RawResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request("POST", path, {
            "Content-Type": "application/json; charset=utf-8"}, body)

    def post_multipart(self, path: str, filename: str, data: bytes,
                       fields: dict[str, str] | None = None) -> RawResponse:
        boundary = "----MosaicBoundary7d91"
        chunks: list[bytes] = []
        for name, value in (fields or {}).items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"image\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        return self.request("POST", path, {
            "Content-Type": f"multipart/form-data; boundary={boundary}"}, body)


def save_cookie(client: RawClient) -> None:
    token = client.cookies.get("mosaic_session")
    if token:
        COOKIE_FILE.write_text(token, encoding="utf-8")


def load_cookie(client: RawClient) -> bool:
    if COOKIE_FILE.exists():
        client.cookies["mosaic_session"] = COOKIE_FILE.read_text(
            encoding="utf-8").strip()
        return True
    return False


def show(response: RawResponse, title: str) -> None:
    print(f"--- {title}: {response.status} "
          f"{STATUS_REASONS.get(response.status, '')}")
    payload = response.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2)
          if payload is not None else "(пустой ответ)")


def main(argv: list[str] | None = None) -> int:
    # Консоль Windows по умолчанию не в UTF-8 — переключаем потоки.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="Сокетный клиент «Мозаики»")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("register", help="регистрация")
    login = sub.add_parser("login", help="вход")
    login.add_argument("username")
    login.add_argument("password")
    sub.add_parser("me", help="текущий пользователь")
    sub.add_parser("feed", help="лента")
    sub.add_parser("dialogs", help="список диалогов")

    search = sub.add_parser("search", help="поиск пользователей")
    search.add_argument("query")

    send = sub.add_parser("send", help="отправить сообщение")
    send.add_argument("username")
    send.add_argument("text")

    dialog = sub.add_parser("dialog", help="переписка")
    dialog.add_argument("username")

    upload = sub.add_parser("upload", help="загрузить картинку")
    upload.add_argument("file")
    upload.add_argument("caption", nargs="?", default="")

    args = parser.parse_args(argv)
    client = RawClient(args.host, args.port)

    if args.command == "register":
        username = input("Логин: ").strip()
        display_name = input("Отображаемое имя: ").strip() or username
        password = input("Пароль: ").strip()
        response = client.post_json("/api/register", {
            "username": username,
            "display_name": display_name,
            "password": password,
        })
        show(response, "Регистрация")
    elif args.command == "login":
        response = client.post_json("/api/login", {
            "username": args.username, "password": args.password})
        show(response, "Вход")
        save_cookie(client)
    elif args.command == "me":
        load_cookie(client)
        show(client.get("/api/me"), "Текущий пользователь")
    elif args.command == "feed":
        load_cookie(client)
        response = client.get("/api/feed?limit=5")
        if response.status != 200:
            show(response, "Лента")
            return 1
        posts = response.json()["posts"]
        print(f"--- Лента: {len(posts)} публикаций")
        for post in posts:
            print(f"  #{post['id']} {post['author']['display_name']}: "
                  f"{post['caption']!r} (лайков: {post['likes']})")
    elif args.command == "dialogs":
        load_cookie(client)
        show(client.get("/api/messages"), "Диалоги")
    elif args.command == "search":
        load_cookie(client)
        # Клиент обязан кодировать не-ASCII символы, как это делает браузер.
        query = urllib.parse.quote(args.query)
        show(client.get(f"/api/users?q={query}"), "Поиск")
    elif args.command == "send":
        load_cookie(client)
        show(client.post_json(f"/api/messages/{args.username}",
                              {"text": args.text}), "Отправка")
    elif args.command == "dialog":
        load_cookie(client)
        show(client.get(f"/api/messages/{args.username}"), "Переписка")
    elif args.command == "upload":
        load_cookie(client)
        data = Path(args.file).read_bytes()
        show(client.post_multipart("/api/posts", Path(args.file).name, data,
                                   {"caption": args.caption}), "Загрузка")
    return 0


if __name__ == "__main__":
    sys.exit(main())
