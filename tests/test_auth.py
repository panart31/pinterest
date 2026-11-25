"""T15–T20: регистрация, вход, сессия, выход (через настоящий сервер)."""

from __future__ import annotations

from tests.support import login, register


# T15
def test_register_creates_user(client):
    response = register(client)
    assert response.status == 201
    user = response.json()["user"]
    assert user["username"] == "ksenia"
    assert user["display_name"] == "Ксения"
    assert "password" not in str(response.json())


# T16
def test_duplicate_username_conflicts(client):
    assert register(client).status == 201
    second = register(client, display_name="Другая Ксения")
    assert second.status == 409
    assert "уже существует" in second.json()["error"]


def test_username_is_case_insensitive(client):
    assert register(client, "Ksenia").status == 201
    assert register(client, "ksenia").status == 409


# T17
def test_short_password_rejected(client):
    response = register(client, password="123")
    assert response.status == 400
    assert "6" in response.json()["error"]


def test_invalid_username_rejected(client):
    response = register(client, username="а")
    assert response.status == 400


# T18
def test_login_success_sets_cookie(client):
    register(client)
    response = login(client)
    assert response.status == 200
    assert response.json()["user"]["username"] == "ksenia"
    cookie = response.header("Set-Cookie")
    assert cookie is not None
    assert "mosaic_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Max-Age=" in cookie


# T19
def test_login_wrong_password(client):
    register(client)
    response = login(client, password="wrong-password")
    assert response.status == 401
    assert response.json()["error"] == "Неверный логин или пароль"


def test_login_unknown_user(client):
    response = login(client, username="nobody")
    assert response.status == 401


# T20
def test_feed_requires_session(client):
    response = client.get("/api/feed")
    assert response.status == 401
    assert "вход" in response.json()["error"]


def test_logout_clears_session(client):
    register(client)
    login(client)
    assert client.get("/api/me").status == 200
    assert client.request("POST", "/api/logout").status == 204
    assert client.get("/api/me").status == 401
