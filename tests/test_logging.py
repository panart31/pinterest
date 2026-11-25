"""Проверки журналирования: строка доступа, аудит и X-Request-Id."""

from __future__ import annotations

import re

from server.core.logging_setup import close_logging, setup_logging
from tests.support import new_user


def test_access_log_contains_request_and_id(server, config):
    setup_logging(config)
    try:
        client = new_user(server.client(), "ksenia")
        response = client.get("/api/feed")
        request_id = response.header("X-Request-Id")
        assert request_id is not None
        assert re.fullmatch(r"[0-9a-f]{8}", request_id)

        text = config.log_path.read_text(encoding="utf-8")
        assert "GET /api/feed HTTP/1.1" in text
        assert request_id in text
        # В строке доступа есть имя пользователя и время выполнения.
        assert "ksenia" in text
        assert "ms id=" in text
    finally:
        close_logging()


def test_audit_log_records_login(server, config):
    setup_logging(config)
    try:
        client = server.client()
        new_user(client, "ksenia")
        text = config.log_path.read_text(encoding="utf-8")
        assert "event=login" in text
        assert "user=ksenia" in text
        assert "result=ok" in text

        client.post_json("/api/login", {"username": "ksenia",
                                        "password": "wrong"})
        text = config.log_path.read_text(encoding="utf-8")
        assert "result=fail" in text
        assert "reason=bad_password" in text
    finally:
        close_logging()
