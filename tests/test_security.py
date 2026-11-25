"""T29–T34: безопасность и корректные коды ошибок."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.config import PROJECT_ROOT
from tests.support import PNG_BYTES, new_user


def auth_client(server, username: str = "ksenia"):
    return new_user(server.client(), username)


# T29
@pytest.mark.parametrize("path", [
    "/uploads/../mosaic.db",
    "/uploads/..%2Fmosaic.db",
    "/uploads/%2e%2e%2fstorage%2fmosaic.db",
    "/static/../server/main.py",
    "/static/..%2F..%2Fconfig.json",
])
def test_path_traversal_blocked(server, path):
    response = server.client().get(path)
    assert response.status == 404
    assert b"password_hash" not in response.body


# T30
def test_sql_injection_in_search_is_harmless(server):
    client = auth_client(server)
    payloads = ["' OR 1=1 --", "'; DROP TABLE users; --", "%' OR '%'='"]
    for payload in payloads:
        response = client.get("/api/users?q=" + payload.replace(" ", "%20"))
        assert response.status == 200
        assert isinstance(response.json()["users"], list)
    # Таблица users по-прежнему доступна: сессия жива.
    assert client.get("/api/me").status == 200


# T31
def test_xss_payload_stored_as_data_not_html(server):
    client = auth_client(server)
    payload = "<script>alert(1)</script>"
    response = client.post_multipart(
        "/api/posts", "x.png", PNG_BYTES, {"caption": payload})
    assert response.status == 201
    assert response.header("Content-Type").startswith("application/json")
    # API отдаёт данные как данные и не пытается «готовить» из них HTML.
    assert response.json()["post"]["caption"] == payload


def test_frontend_uses_textcontent_not_innerhtml():
    """Статическая проверка: SPA не вставляет данные через innerHTML."""
    script = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in script
    assert "textContent" in script


# T32
def test_upload_over_limit_is_413(server):
    client = auth_client(server)
    big = PNG_BYTES + b"\x00" * (80 * 1024)
    response = client.post_multipart("/api/posts", "big.png", big,
                                     {"caption": "Слишком большой"})
    assert response.status == 413


# T33
def test_method_not_allowed(server):
    client = auth_client(server)
    response = client.get("/api/posts")
    assert response.status == 405
    assert "POST" in response.header("Allow")


# T34
def test_unknown_resource_404(server):
    client = auth_client(server)
    assert client.get("/api/does-not-exist").status == 404
    assert client.get("/uploads/missing.png").status == 404
    assert client.get("/static/missing.js").status == 404


def test_non_image_rejected_by_signature(server):
    client = auth_client(server)
    fake = b"MZ\x90\x00" + b"\x00" * 128  # начало исполняемого файла Windows
    response = client.post_multipart("/api/posts", "virus.png", fake,
                                     {"caption": "Не картинка"})
    assert response.status == 400
    assert "JPEG" in response.json()["error"]


def test_uploaded_name_is_generated(server):
    """Сервер игнорирует исходное имя и хранит файл под UUID."""
    client = auth_client(server)
    response = client.post_multipart("/api/posts", "../../evil.png", PNG_BYTES)
    assert response.status == 201
    image_url = response.json()["post"]["image_url"]
    stored = image_url.rsplit("/", 1)[-1]
    assert "evil" not in stored
    assert stored.endswith(".png") and len(stored) == 36


def test_oversized_json_body_rejected(server):
    client = auth_client(server)
    # Тело больше max_body (128 КБ в тестовой конфигурации).
    body = b'{"text":"' + b"a" * (200 * 1024) + b'"}'
    response = client.request("POST", "/api/messages/ksenia", {
        "Content-Type": "application/json"}, body)
    assert response.status == 413
