"""T01–T08: юнит-тесты разбора HTTP-запроса."""

from __future__ import annotations

import pytest

from server.http.request import (
    HTTPError,
    percent_decode,
    parse_query_string,
    read_request,
)


class FakeSocket:
    """Сокет-заглушка: отдаёт заранее заданные куски данных."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)

    def recv(self, size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks[0]
        if len(chunk) <= size:
            return self.chunks.pop(0)
        self.chunks[0] = chunk[size:]
        return chunk[:size]


def build(method: str = "GET", path: str = "/", headers: dict[str, str] | None = None,
          body: bytes = b"") -> bytes:
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    if body:
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


# T01
def test_request_line_parsed():
    request = read_request(FakeSocket([build("GET", "/api/feed?limit=5")]))
    assert request.method == "GET"
    assert request.path == "/api/feed"
    assert request.version == "HTTP/1.1"
    assert request.query_one("limit") == "5"


# T02
def test_headers_are_case_insensitive():
    raw = build("POST", "/api/login", {"Content-Type": "application/json",
                                       "X-Custom": "42"})
    request = read_request(FakeSocket([raw]))
    assert request.header("content-type") == "application/json"
    assert request.header("CONTENT-TYPE") == "application/json"
    assert request.header("x-custom") == "42"
    assert request.header("missing") is None


# T03
def test_body_read_by_content_length_in_chunks():
    body = "привет".encode("utf-8")
    raw = build("POST", "/api/messages/artem", {"Content-Type": "application/json"},
                b'{"text":"' + body + b'"}')
    # Режем поток на мелкие куски, как это делает сеть.
    chunks = [raw[i:i + 7] for i in range(0, len(raw), 7)]
    request = read_request(FakeSocket(chunks))
    assert request.json_body()["text"] == "привет"
    assert len(request.body) == len(raw) - raw.index(b"\r\n\r\n") - 4


# T04
def test_broken_request_line_gives_400():
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([b"GET /only-two-parts\r\n\r\n"]))
    assert error.value.status == 400


# T05
def test_header_limit_enforced():
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([b"GET / HTTP/1.1\r\nHost: x\r\n"]),
                     max_header=64)
    assert error.value.status == 400
    assert "заголовк" in error.value.message.lower()


# T06
def test_utf8_path_and_query():
    raw = build("GET", "/api/users?q=%D0%9A%D1%81%D0%B5%D0%BD%D0%B8%D1%8F")
    request = read_request(FakeSocket([raw]))
    assert request.query_one("q") == "Ксения"
    assert percent_decode("%D0%9C%D0%BE%D0%B7%D0%B0%D0%B8%D0%BA%D0%B0") == "Мозаика"


# T07
def test_query_string_repeated_keys_and_plus():
    query = parse_query_string("tag=one&tag=two&q=%D0%B4%D0%B2%D0%B0+%D1%81%D0%BB%D0%BE%D0%B2%D0%B0")
    assert query["tag"] == ["one", "two"]
    assert query["q"] == ["два слова"]


# T08
def test_empty_body_is_allowed():
    request = read_request(FakeSocket([build("POST", "/api/logout")]))
    assert request.body == b""
    with pytest.raises(HTTPError):
        request.json_body()


def test_missing_host_rejected():
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([b"GET / HTTP/1.1\r\n\r\n"]))
    assert error.value.status == 400
    assert "Host" in error.value.message


def test_transfer_encoding_rejected():
    raw = (b"POST /api/feed HTTP/1.1\r\nHost: x\r\n"
           b"Transfer-Encoding: chunked\r\n\r\n")
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([raw]))
    assert error.value.status == 400


def test_bad_content_length_rejected():
    raw = (b"POST /api/feed HTTP/1.1\r\nHost: x\r\n"
           b"Content-Length: twelve\r\n\r\n")
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([raw]))
    assert error.value.status == 400


def test_body_limit_gives_413():
    raw = (b"POST /api/posts HTTP/1.1\r\nHost: x\r\n"
           b"Content-Length: 999999\r\n\r\n")
    with pytest.raises(HTTPError) as error:
        read_request(FakeSocket([raw]), max_body=1024)
    assert error.value.status == 413
