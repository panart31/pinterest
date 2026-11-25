"""T35–T38: интеграционные сценарии через настоящие сокеты."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client_raw.raw_client import RawClient  # noqa: E402
from tests.support import PNG_BYTES, ServerFixture, make_config  # noqa: E402


# T35
def test_full_scenario_with_raw_client(server):
    """Полный путь: регистрация → вход → загрузка → лента → сообщение."""
    ksenia = RawClient("127.0.0.1", server.server.port)
    registered = ksenia.post_json("/api/register", {
        "username": "ksenia", "password": "secret123",
        "display_name": "Ксения"})
    assert registered.status == 201

    assert ksenia.post_json("/api/login", {
        "username": "ksenia", "password": "secret123"}).status == 200
    assert "mosaic_session" in ksenia.cookies

    uploaded = ksenia.post_multipart("/api/posts", "cat.png", PNG_BYTES,
                                     {"caption": "Кот"})
    assert uploaded.status == 201

    feed = ksenia.get("/api/feed").json()
    assert feed["total"] == 1
    assert feed["posts"][0]["caption"] == "Кот"

    artem = RawClient("127.0.0.1", server.server.port)
    artem.post_json("/api/register", {
        "username": "artem", "password": "secret123",
        "display_name": "Артём"})
    artem.post_json("/api/login", {
        "username": "artem", "password": "secret123"})
    sent = artem.post_json("/api/messages/ksenia", {"text": "Привет"})
    assert sent.status == 201

    dialog = ksenia.get("/api/messages/artem").json()
    assert dialog["messages"][0]["text"] == "Привет"


# T36
def test_ten_parallel_clients(server):
    """Десять одновременных подключений не мешают друг другу."""
    clients = []
    for index in range(10):
        client = server.client()
        username = f"user{index}"
        client.post_json("/api/register", {
            "username": username, "password": "secret123",
            "display_name": f"Пользователь {index}"})
        assert client.post_json("/api/login", {
            "username": username, "password": "secret123"}).status == 200
        clients.append((client, username))

    results: list[tuple[str, int]] = []
    lock = threading.Lock()

    def worker(client, username):
        response = client.post_multipart(
            "/api/posts", f"{username}.png", PNG_BYTES,
            {"caption": f"Пост {username}"})
        with lock:
            results.append((username, response.status))

    threads = [threading.Thread(target=worker, args=pair) for pair in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(results) == 10
    assert all(status == 201 for _, status in results)

    feed = clients[0][0].get("/api/feed?limit=50").json()
    assert feed["total"] == 10
    assert len({post["author"]["username"] for post in feed["posts"]}) == 10


# T37
def test_data_survives_restart(tmp_path):
    """Данные сохраняются: после перезапуска лента и пользователи на месте."""
    config = make_config(tmp_path)
    first = ServerFixture(config).start()
    try:
        client = first.client()
        client.post_json("/api/register", {
            "username": "ksenia", "password": "secret123",
            "display_name": "Ксения"})
        client.post_json("/api/login", {
            "username": "ksenia", "password": "secret123"})
        client.post_multipart("/api/posts", "photo.png", PNG_BYTES,
                              {"caption": "До перезапуска"})
    finally:
        first.stop()

    second = ServerFixture(config).start()
    try:
        client = second.client()
        assert client.post_json("/api/login", {
            "username": "ksenia", "password": "secret123"}).status == 200
        feed = client.get("/api/feed").json()
        assert feed["total"] == 1
        assert feed["posts"][0]["caption"] == "До перезапуска"
        image = client.get(feed["posts"][0]["image_url"])
        assert image.status == 200
        assert image.body == PNG_BYTES
    finally:
        second.stop()


# T38
def test_two_users_exchange_messages(server):
    ksenia = server.client()
    artem = server.client()
    for client, name in ((ksenia, "ksenia"), (artem, "artem")):
        client.post_json("/api/register", {
            "username": name, "password": "secret123",
            "display_name": name.title()})
        client.post_json("/api/login", {
            "username": name, "password": "secret123"})

    ksenia.post_json("/api/messages/artem", {"text": "Как дела?"})
    artem.post_json("/api/messages/ksenia", {"text": "Отлично!"})
    ksenia.post_json("/api/messages/artem", {"text": "Рад за тебя"})

    artem_dialogs = artem.get("/api/messages").json()
    assert artem_dialogs["dialogs"][0]["unread"] == 2
    assert artem_dialogs["dialogs"][0]["last_text"] == "Рад за тебя"

    artem.request("POST", "/api/messages/ksenia/read")
    assert artem.get("/api/messages").json()["unread_total"] == 0

    dialog = ksenia.get("/api/messages/artem").json()
    assert [message["text"] for message in dialog["messages"]] == [
        "Как дела?", "Отлично!", "Рад за тебя"]


def test_parallel_likes_are_consistent(server):
    """Десять лайков от разных пользователей дают ровно 10."""
    author = server.client()
    author.post_json("/api/register", {
        "username": "author", "password": "secret123", "display_name": "Автор"})
    author.post_json("/api/login", {
        "username": "author", "password": "secret123"})
    post_id = author.post_multipart("/api/posts", "p.png", PNG_BYTES,
                                    {"caption": "Пост"}).json()["post"]["id"]

    clients = []
    for index in range(10):
        client = server.client()
        client.post_json("/api/register", {
            "username": f"fan{index}", "password": "secret123",
            "display_name": f"Фанат {index}"})
        client.post_json("/api/login", {
            "username": f"fan{index}", "password": "secret123"})
        clients.append(client)

    threads = [
        threading.Thread(target=client.request,
                         args=("POST", f"/api/posts/{post_id}/like"))
        for client in clients
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    post = author.get("/api/feed").json()["posts"][0]
    assert post["likes"] == 10
