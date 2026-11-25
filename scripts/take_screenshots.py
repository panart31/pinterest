#!/usr/bin/env python3
"""Снимает скриншоты интерфейса через headless Edge и DevTools Protocol.

Это вспомогательный инструмент разработчика, а не часть сервера.
Ему нужен установленный Microsoft Edge и пакет websocket-client:

    py -m pip install websocket-client
    py scripts/take_screenshots.py

Скрипт сам запускает сервер на свободном порту, наполняет базу
демо-данными (если она пуста) и складывает PNG в docs/screenshots.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_demo import seed  # noqa: E402
from server.app import Application  # noqa: E402
from server.config import Config, load_config  # noqa: E402
from server.core.server import HTTPServer  # noqa: E402

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

SHOTS = PROJECT_ROOT / "docs" / "screenshots"
DEBUG_PORT = 9333
VIEWPORT = (1440, 900)


class Browser:
    """Минимальный клиент DevTools Protocol поверх websocket."""

    def __init__(self) -> None:
        self._id = 0
        self.socket = websocket.create_connection(self._ws_url(), timeout=20)
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("DOM.enable")

    @staticmethod
    def _ws_url() -> str:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=2) as r:
                    targets = json.loads(r.read().decode("utf-8"))
                for target in targets:
                    if target.get("type") == "page":
                        return target["webSocketDebuggerUrl"]
            except OSError:
                pass
            time.sleep(0.4)
        raise RuntimeError("Не удалось подключиться к Edge")

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        request = {"id": self._id, "method": method, "params": params or {}}
        self.socket.send(json.dumps(request))
        while True:
            message = json.loads(self.socket.recv())
            if message.get("id") == self._id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def eval(self, expression: str, await_promise: bool = False):
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 15.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.eval(expression):
                return
            time.sleep(0.15)
        raise RuntimeError(f"Не дождались: {expression}")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})
        time.sleep(0.6)

    def shot(self, name: str) -> None:
        data = self.send("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": False})
        path = SHOTS / name
        path.write_bytes(base64.b64decode(data["data"]))
        print(f"  сохранено: {path.name}")

    def set_file(self, selector: str, file_path: Path) -> None:
        document = self.send("DOM.getDocument")
        node = self.send("DOM.querySelector", {
            "nodeId": document["root"]["nodeId"], "selector": selector})
        self.send("DOM.setFileInputFiles", {
            "nodeId": node["nodeId"], "files": [str(file_path)]})


def start_edge() -> subprocess.Popen:
    executable = next((path for path in EDGE_PATHS if Path(path).exists()), None)
    if executable is None:
        raise SystemExit("Microsoft Edge не найден")
    profile = tempfile.mkdtemp(prefix="mosaic-shots-")
    command = [
        executable,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile}",
        f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}",
        "about:blank",
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def start_server(config, port: int) -> tuple[HTTPServer, Application]:
    application = Application(config)
    server = HTTPServer(config, application)
    server.start()
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, application


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    SHOTS.mkdir(parents=True, exist_ok=True)

    config = load_config([]).ensure_dirs()
    seed(reset=False)

    server, application = start_server(config, 8000)
    base = "http://127.0.0.1:8000"

    # Второй сервер с чистой базой — для кадра «пустая лента».
    empty_dir = Path(tempfile.mkdtemp(prefix="mosaic-empty-"))
    empty_config = Config(
        host="127.0.0.1", port=8001,
        db_path=empty_dir / "empty.db",
        uploads_dir=empty_dir / "uploads",
        log_path=empty_dir / "server.log",
    ).ensure_dirs()
    empty_server, empty_application = start_server(empty_config, 8001)
    empty_base = "http://127.0.0.1:8001"

    edge = start_edge()
    try:
        browser = Browser()
        browser.send("Emulation.setDeviceMetricsOverride", {
            "width": VIEWPORT[0], "height": VIEWPORT[1],
            "deviceScaleFactor": 1, "mobile": False})

        print("Снимаем страницу входа…")
        browser.navigate(base + "/login")
        browser.wait_for("document.querySelector('.auth-card') !== null")
        browser.shot("01_login.png")

        browser.eval("document.querySelector('[data-mode=register]').click()")
        time.sleep(0.4)
        browser.shot("02_register.png")

        print("Входим под демо-пользователем…")
        status = browser.eval(
            "fetch('/api/login', {method:'POST', "
            "headers:{'Content-Type':'application/json'}, "
            "body: JSON.stringify({username:'ksenia', password:'secret123'})})"
            ".then(r => r.status)", await_promise=True)
        if status != 200:
            raise RuntimeError(f"Вход не удался: {status}")

        browser.navigate(base + "/")
        browser.wait_for("document.querySelectorAll('.card').length > 1")
        time.sleep(0.6)
        browser.shot("03_feed.png")

        print("Ставим лайк…")
        browser.eval("document.querySelector('.like').click()")
        time.sleep(1.0)
        browser.shot("04_feed_like.png")

        print("Открываем фото крупно…")
        # Открываем публикацию Ксении: у автора видна кнопка «Удалить».
        browser.eval(
            "(() => {const cards = [...document.querySelectorAll('.card')];"
            "const own = cards.find(c => c.querySelector('.card__caption')"
            ".textContent.includes('Закат')) || cards[0];"
            "own.querySelector('.card__media').click();})()")
        browser.wait_for("document.getElementById('post-dialog').open")
        browser.wait_for(
            "document.querySelectorAll('.comment').length > 0 || "
            "!document.getElementById('comments-empty')"
            ".classList.contains('hidden')")
        time.sleep(0.6)
        browser.shot("11_post_view.png")
        browser.eval("document.getElementById('post-close').click()")
        time.sleep(0.3)

        print("Открываем диалог загрузки…")
        browser.eval("document.getElementById('upload-open').click()")
        time.sleep(0.4)
        demo_image = Path(config.uploads_dir) / "_demo" / "peach.png"
        if demo_image.exists():
            browser.set_file("#upload-file", demo_image)
            time.sleep(0.6)
        browser.shot("05_upload_dialog.png")
        browser.eval("document.getElementById('upload-cancel').click()")
        time.sleep(0.3)

        print("Ищем пользователя…")
        browser.eval(
            "(() => {const i = document.getElementById('search-input');"
            "i.value = 'закат'; i.dispatchEvent(new Event('input', {bubbles:true}));})()")
        time.sleep(1.2)
        browser.shot("06_search.png")
        browser.eval("document.getElementById('search-input').value = '';"
                     "document.getElementById('search-results')"
                     ".classList.add('hidden')")

        print("Открываем сообщения…")
        browser.eval("location.hash = '#messages/artem'")
        browser.wait_for("document.querySelectorAll('.bubble').length > 0")
        time.sleep(0.6)
        browser.shot("07_messages.png")

        print("Открываем свой профиль…")
        browser.eval("location.hash = '#profile/ksenia'")
        browser.wait_for("document.getElementById('profile-name')"
                         ".textContent !== 'Загрузка…'")
        time.sleep(0.6)
        browser.shot("08_profile.png")

        print("Снимаем ответ 401…")
        # Выходим, чтобы запрос к API был без сессии.
        browser.eval("fetch('/api/logout', {method:'POST'})", await_promise=True)
        browser.navigate(base + "/api/feed")
        time.sleep(0.6)
        browser.shot("09_api_401.png")

        print("Снимаем пустую ленту на чистой базе…")
        browser.navigate(empty_base + "/login")
        browser.wait_for("document.querySelector('.auth-card') !== null")
        browser.eval(
            "fetch('/api/register', {method:'POST', "
            "headers:{'Content-Type':'application/json'}, "
            "body: JSON.stringify({username:'newuser', "
            "display_name:'Новый пользователь', password:'secret123'})})"
            ".then(r => r.status)", await_promise=True)
        browser.eval(
            "fetch('/api/login', {method:'POST', "
            "headers:{'Content-Type':'application/json'}, "
            "body: JSON.stringify({username:'newuser', password:'secret123'})})"
            ".then(r => r.status)", await_promise=True)
        browser.navigate(empty_base + "/")
        browser.wait_for(
            "document.getElementById('feed-empty') && "
            "!document.getElementById('feed-empty').classList.contains('hidden')")
        time.sleep(0.5)
        browser.shot("10_empty_feed.png")

        print("Готово: скриншоты в docs/screenshots")
    finally:
        edge.terminate()
        try:
            edge.wait(timeout=10)
        except subprocess.TimeoutExpired:
            edge.kill()
        server.shutdown()
        application.close()
        empty_server.shutdown()
        empty_application.close()
        shutil.rmtree(empty_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
