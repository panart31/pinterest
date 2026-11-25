"""T21–T28: работа API ленты, публикаций, поиска и сообщений."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.support import PNG_BYTES, TestClient, login, new_user, register


def auth_client(server, username: str = "ksenia",
                display_name: str | None = None) -> TestClient:
    client = server.client()
    return new_user(client, username, display_name=display_name)


def upload(client: TestClient, caption: str = "Тестовая карточка",
           data: bytes = PNG_BYTES, filename: str = "photo.png"):
    return client.post_multipart("/api/posts", filename, data,
                                 {"caption": caption})


# T21
def test_empty_feed(server):
    client = auth_client(server)
    response = client.get("/api/feed")
    assert response.status == 200
    body = response.json()
    assert body["posts"] == []
    assert body["total"] == 0


# T22
def test_feed_pagination(server):
    client = auth_client(server)
    for index in range(5):
        assert upload(client, f"Пост {index}").status == 201

    first = client.get("/api/feed?limit=2").json()
    second = client.get("/api/feed?limit=2&offset=2").json()
    assert first["total"] == 5
    assert len(first["posts"]) == 2
    assert len(second["posts"]) == 2
    assert first["posts"][0]["id"] != second["posts"][0]["id"]
    # Сортировка по новизне: первый пост — последний загруженный.
    assert first["posts"][0]["caption"] == "Пост 4"


# T23
def test_upload_post_and_fetch_file(server):
    client = auth_client(server, "ksenia", "Ксения")
    response = upload(client, "Кот")
    assert response.status == 201
    post = response.json()["post"]
    assert post["caption"] == "Кот"
    assert post["likes"] == 0
    assert post["author"]["username"] == "ksenia"
    assert post["image_url"].startswith("/uploads/")

    image = client.get(post["image_url"])
    assert image.status == 200
    assert image.header("Content-Type") == "image/png"
    assert image.body == PNG_BYTES


# T24
def test_like_and_unlike(server):
    author = auth_client(server, "ksenia")
    upload(author)
    post_id = author.get("/api/feed").json()["posts"][0]["id"]

    fan = auth_client(server, "artem")
    liked = fan.request("POST", f"/api/posts/{post_id}/like")
    assert liked.status == 200
    assert liked.json() == {"liked": True, "likes": 1}

    unliked = fan.request("POST", f"/api/posts/{post_id}/like")
    assert unliked.json() == {"liked": False, "likes": 0}

    missing = fan.request("POST", "/api/posts/99999/like")
    assert missing.status == 404


# T25
def test_send_message(server):
    ksenia = auth_client(server, "ksenia")
    artem = auth_client(server, "artem")
    response = artem.post_json("/api/messages/ksenia", {"text": "Привет!"})
    assert response.status == 201
    message = response.json()["message"]
    assert message["text"] == "Привет!"
    assert message["mine"] is True

    dialog = ksenia.get("/api/messages/artem").json()
    assert len(dialog["messages"]) == 1
    assert dialog["messages"][0]["mine"] is False


# T26
def test_dialogs_list(server):
    ksenia = auth_client(server, "ksenia")
    artem = auth_client(server, "artem")
    artem.post_json("/api/messages/ksenia", {"text": "Первое"})
    artem.post_json("/api/messages/ksenia", {"text": "Второе"})

    dialogs = ksenia.get("/api/messages").json()["dialogs"]
    assert len(dialogs) == 1
    assert dialogs[0]["user"]["username"] == "artem"
    assert dialogs[0]["last_text"] == "Второе"
    assert dialogs[0]["unread"] == 2
    assert dialogs[0]["last_mine"] is False


# T27
def test_unread_counter(server):
    ksenia = auth_client(server, "ksenia")
    artem = auth_client(server, "artem")
    artem.post_json("/api/messages/ksenia", {"text": "Раз"})
    artem.post_json("/api/messages/ksenia", {"text": "Два"})
    response = ksenia.get("/api/messages/artem")
    assert response.json()["unread_total"] == 2


# T28
def test_mark_read(server):
    ksenia = auth_client(server, "ksenia")
    artem = auth_client(server, "artem")
    artem.post_json("/api/messages/ksenia", {"text": "Прочитай меня"})

    read = ksenia.request("POST", "/api/messages/artem/read")
    assert read.status == 200
    assert read.json()["updated"] == 1
    assert read.json()["unread_total"] == 0

    dialogs = ksenia.get("/api/messages").json()["dialogs"]
    assert dialogs[0]["unread"] == 0


def test_message_after_id_polling(server):
    ksenia = auth_client(server, "ksenia")
    artem = auth_client(server, "artem")
    first = artem.post_json("/api/messages/ksenia", {"text": "Старое"}).json()
    artem.post_json("/api/messages/ksenia", {"text": "Новое"})

    fresh = ksenia.get(
        f"/api/messages/artem?after_id={first['message']['id']}").json()
    assert [message["text"] for message in fresh["messages"]] == ["Новое"]


def test_user_search(server):
    ksenia = auth_client(server, "ksenia")
    auth_client(server, "artem", "Артём")
    found = ksenia.get("/api/users?q=" + quote("арт")).json()["users"]
    assert len(found) == 1
    assert found[0]["display_name"] == "Артём"
    # Себя в результатах не показываем.
    assert ksenia.get("/api/users?q=ksen").json()["users"] == []


def test_author_filter(server):
    ksenia = auth_client(server, "ksenia")
    upload(ksenia, "От Ксении")
    artem = auth_client(server, "artem")
    upload(artem, "От Артёма")

    feed = ksenia.get("/api/feed?author=artem").json()
    assert feed["total"] == 1
    assert feed["posts"][0]["caption"] == "От Артёма"
    assert feed["user"]["username"] == "artem"


def test_cannot_message_self_or_unknown(server):
    ksenia = auth_client(server, "ksenia")
    assert ksenia.post_json("/api/messages/ksenia", {"text": "Я"}).status == 400
    assert ksenia.post_json("/api/messages/nobody", {"text": "Я"}).status == 404


def test_empty_message_rejected(server):
    ksenia = auth_client(server, "ksenia")
    auth_client(server, "artem")
    assert ksenia.post_json("/api/messages/artem", {"text": "   "}).status == 400


def test_invalid_pagination_values(server):
    client = auth_client(server)
    assert client.get("/api/feed?limit=abc").status == 400
    # Отрицательный offset приводится к нулю, limit ограничивается сверху.
    assert client.get("/api/feed?offset=-5&limit=1000").status == 200


def test_login_via_form(server):
    register(server.client())
    response = server.client().post_form("/api/login", {
        "username": "ksenia", "password": "secret123"})
    assert response.status == 200
    assert response.json()["user"]["username"] == "ksenia"


def test_delete_own_post(server):
    author = auth_client(server)
    post = upload(author).json()["post"]
    image_url = post["image_url"]

    response = author.request("POST", f"/api/posts/{post['id']}/delete")
    assert response.status == 204
    assert author.get("/api/feed").json()["total"] == 0
    assert author.get(image_url).status == 404
    assert author.get(f"/api/posts/{post['id']}").status == 404


def test_cannot_delete_foreign_post(server):
    author = auth_client(server, "ksenia")
    post = upload(author).json()["post"]

    stranger = auth_client(server, "artem")
    response = stranger.request("POST", f"/api/posts/{post['id']}/delete")
    assert response.status == 403
    assert author.get("/api/feed").json()["total"] == 1


def test_delete_missing_or_without_session(server):
    author = auth_client(server)
    assert author.request("POST", "/api/posts/9999/delete").status == 404

    post = upload(author).json()["post"]
    anonymous = server.client()
    assert anonymous.request(
        "POST", f"/api/posts/{post['id']}/delete").status == 401
