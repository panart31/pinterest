#!/usr/bin/env python3
"""Измерение производительности сервера на учебной нагрузке.

Скрипт поднимает отдельный экземпляр сервера на свободном порту,
создаёт временную базу, наполняет её десятью публикациями и измеряет
время операций через сокетный клиент.

Запуск:
    python scripts/benchmark.py
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client_raw.raw_client import RawClient  # noqa: E402
from server.app import Application  # noqa: E402
from server.config import Config  # noqa: E402
from server.core.clock import iso_now  # noqa: E402
from server.core.security import hash_password  # noqa: E402
from server.core.server import HTTPServer  # noqa: E402

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
    "426082")


def measure(action, repeat: int) -> tuple[float, float, float]:
    """Возвращает среднее, 95-й процентиль и максимум в миллисекундах."""
    samples: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
    return statistics.mean(samples), p95, samples[-1]


def run_benchmark(base: Path) -> list[tuple[str, float, float, float]]:
    config = Config(
        host="127.0.0.1",
        port=0,
        db_path=base / "bench.db",
        uploads_dir=base / "uploads",
        log_path=base / "bench.log",
        max_upload=5 * 1024 * 1024,
        max_body=6 * 1024 * 1024,
    ).ensure_dirs()

    application = Application(config)
    server = HTTPServer(config, application)
    server.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.port

    salt, digest = hash_password("secret123")
    user = application.repo.create_user("bench", "Бенчмарк", salt, digest,
                                        iso_now())
    post_ids = []
    for index in range(10):
        filename = application.storage.save(PNG, "png")
        post_ids.append(application.repo.create_post(
            user["id"], filename, f"Публикация {index}", iso_now()))

    client = RawClient("127.0.0.1", port)
    assert client.post_json("/api/login", {
        "username": "bench", "password": "secret123"}).status == 200

    results: list[tuple[str, float, float, float]] = []

    mean, p95, maximum = measure(
        lambda: client.post_json("/api/login", {
            "username": "bench", "password": "secret123"}), 20)
    results.append(("Вход (PBKDF2, 200 000 итераций)", mean, p95, maximum))

    mean, p95, maximum = measure(
        lambda: client.get("/api/feed?limit=12"), 100)
    results.append(("Лента, 10 публикаций", mean, p95, maximum))

    counter = {"value": 0}

    def toggle_like() -> None:
        post_id = post_ids[counter["value"] % len(post_ids)]
        counter["value"] += 1
        client.request("POST", f"/api/posts/{post_id}/like")

    mean, p95, maximum = measure(toggle_like, 100)
    results.append(("Лайк / анлайк", mean, p95, maximum))

    big_image = PNG + b"\x00" * (1024 * 1024)
    mean, p95, maximum = measure(
        lambda: client.post_multipart("/api/posts", "big.png", big_image,
                                      {"caption": "1 МБ"}), 10)
    results.append(("Загрузка файла 1 МБ", mean, p95, maximum))

    def parallel_worker() -> None:
        local = RawClient("127.0.0.1", port)
        local.cookies = dict(client.cookies)
        for _ in range(10):
            local.get("/api/feed?limit=12")

    started = time.perf_counter()
    threads = [threading.Thread(target=parallel_worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = (time.perf_counter() - started) * 1000
    results.append(("10 клиентов × 10 запросов (100 запросов)",
                    elapsed, elapsed, elapsed))

    print(f"Порт: {port}; публикаций: {len(post_ids)}; "
          f"Python {sys.version.split()[0]}")
    print(f"{'Операция':44s} {'среднее':>10s} {'p95':>10s} {'макс':>10s}")
    for name, mean, p95, maximum in results:
        print(f"{name:44s} {mean:8.1f} мс {p95:8.1f} мс {maximum:8.1f} мс")

    server.shutdown()
    application.close()
    return results


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    # ignore_cleanup_errors: на Windows файл SQLite освобождается
    # с небольшой задержкой после закрытия соединений.
    with tempfile.TemporaryDirectory(prefix="mosaic-bench-",
                                     ignore_cleanup_errors=True) as folder:
        run_benchmark(Path(folder))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
