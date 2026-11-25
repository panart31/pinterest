"""Тесты комментариев, поиска по подписям и скачивания фото."""

from __future__ import annotations

from urllib.parse import quote

from tests.support import PNG_BYTES, new_user


def auth_client(server, username: str = "ksenia",
                display_name: str | None = None):
    return new_user(server.client(), username, display_name=display_name)


def upload(client, caption: str = "Закат на набережной"):
    response = client.post_multipart("/api/posts", "photo.png", PNG_BYTES,
                                     {"caption": caption})
    assert response.status == 201
    return response.json()["post"]


def test_comment_create_and_list(server):
    author = auth_client(server, "ksenia")
    post = upload(author)

    guest = auth_client(server, "artem")
    created = guest.post_json(f"/api/posts/{post['id']}/comments",
                              {"text": "Отличный кадр"})
    assert created.status == 201
    comment = created.json()["comment"]
    assert comment["text"] == "Отличный кадр"
    assert comment["author"]["username"] == "artem"

    listed = author.get(f"/api/posts/{post['id']}/comments").json()
    assert listed["total"] == 1
    assert listed["comments"][0]["author"]["display_name"] == "artem"

    # Счётчик комментариев виден в ленте и в карточке публикации.
    feed_post = author.get("/api/feed").json()["posts"][0]
    assert feed_post["comments"] == 1
    assert author.get(f"/api/posts/{post['id']}").json()["post"]["comments"] == 1


def test_comment_validation(server):
    author = auth_client(server)
    post = upload(author)

    assert author.post_json(f"/api/posts/{post['id']}/comments",
                            {"text": "   "}).status == 400
    assert author.post_json("/api/posts/9999/comments",
                            {"text": "Текст"}).status == 404
    anonymous = server.client()
    assert anonymous.post_json(f"/api/posts/{post['id']}/comments",
                               {"text": "Текст"}).status == 401


def test_search_finds_posts_by_caption(server):
    author = auth_client(server, "ksenia", "Ксения Дутикова")
    upload(author, "Закат на набережной — поймала свет")
    upload(author, "Море в четверг")

    found = author.get("/api/search?q=" + quote("закат")).json()
    assert len(found["posts"]) == 1
    assert "Закат" in found["posts"][0]["caption"]

    # Поиск по имени по-прежнему находит людей.
    people = author.get("/api/search?q=" + quote("ксен")).json()
    assert people["users"] == []  # себя исключаем
    other = auth_client(server, "artem")
    people = other.get("/api/search?q=" + quote("ксен")).json()
    assert people["users"][0]["username"] == "ksenia"


def test_search_ignores_case_and_empty_query(server):
    author = auth_client(server)
    upload(author, "ЛЕС ПОСЛЕ ДОЖДЯ")
    assert author.get("/api/search?q=" + quote("лес")).json()["posts"]
    empty = author.get("/api/search?q=").json()
    assert empty == {"users": [], "posts": []}


def test_download_post(server):
    author = auth_client(server)
    post = upload(author)

    response = author.get(f"/api/posts/{post['id']}/download")
    assert response.status == 200
    assert response.body == PNG_BYTES
    assert response.header("Content-Type") == "image/png"
    assert "attachment" in response.header("Content-Disposition")
    assert f"mosaic-{post['id']}.png" in response.header("Content-Disposition")

    assert author.get("/api/posts/9999/download").status == 404
