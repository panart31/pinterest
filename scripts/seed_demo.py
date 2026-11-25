#!/usr/bin/env python3
"""Наполняет базу демонстрационными данными.

Скрипт создаёт пользователей, изображения и переписку, чтобы лента
и сообщения выглядели живыми на защите. Картинки генерируются
встроенным PNG-кодировщиком — никаких сторонних библиотек.

Запуск (сервер при этом может быть остановлен):
    python scripts/seed_demo.py
    python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app import Application  # noqa: E402
from server.config import load_config  # noqa: E402
from server.core.clock import iso_now  # noqa: E402
from server.core.security import hash_password  # noqa: E402

Color = tuple[int, int, int]


# ----------------------------------------------------------------- картинки
def mix(first: Color, second: Color, ratio: float) -> Color:
    """Линейно смешивает два цвета."""
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(a + (b - a) * ratio) for a, b in zip(first, second))  # type: ignore[return-value]


class Canvas:
    """Простой RGB-холст с градиентом и фигурами."""

    def __init__(self, width: int, height: int, top: Color, bottom: Color,
                 diagonal: float = 0.35):
        self.width = width
        self.height = height
        step = width + height * diagonal
        self.pixels: list[list[Color]] = [
            [mix(top, bottom, (x + y * diagonal) / step) for x in range(width)]
            for y in range(height)
        ]

    def circle(self, cx: int, cy: int, radius: int, color: Color,
               alpha: float = 0.8) -> None:
        """Рисует круг с наложением цвета."""
        for y in range(max(0, cy - radius), min(self.height, cy + radius + 1)):
            row = self.pixels[y]
            for x in range(max(0, cx - radius), min(self.width, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                    row[x] = mix(row[x], color, alpha)

    def rect(self, x0: int, y0: int, x1: int, y1: int, color: Color,
             alpha: float = 0.8) -> None:
        for y in range(max(0, y0), min(self.height, y1)):
            row = self.pixels[y]
            for x in range(max(0, x0), min(self.width, x1)):
                row[x] = mix(row[x], color, alpha)

    def save(self, path: Path) -> None:
        """Сохраняет холст в PNG без внешних библиотек."""
        raw = bytearray()
        for row in self.pixels:
            raw.append(0)  # фильтр None
            for red, green, blue in row:
                raw.extend((red, green, blue))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        payload = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
                   chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
                   chunk(b"IEND", b""))
        path.write_bytes(payload)


def make_images(folder: Path) -> list[Path]:
    """Создаёт набор открыток для ленты."""
    folder.mkdir(parents=True, exist_ok=True)
    specs = [
        ("sunset", 600, 780, (247, 178, 103), (214, 57, 111), [
            ("circle", 300, 250, 120, (255, 236, 179), 0.85),
            ("rect", 0, 560, 600, 780, (120, 40, 90), 0.55),
        ]),
        ("sea", 720, 520, (126, 214, 223), (32, 90, 160), [
            ("rect", 0, 300, 720, 340, (255, 255, 255), 0.35),
            ("circle", 560, 130, 70, (255, 245, 200), 0.75),
        ]),
        ("lilac", 560, 720, (196, 181, 253), (91, 71, 214), [
            ("rect", 80, 120, 240, 280, (255, 255, 255), 0.35),
            ("rect", 300, 320, 480, 500, (255, 255, 255), 0.22),
        ]),
        ("mint", 640, 640, (167, 243, 208), (16, 122, 104), [
            ("circle", 320, 320, 190, (255, 255, 255), 0.25),
            ("circle", 480, 180, 90, (16, 80, 70), 0.35),
        ]),
        ("sand", 600, 840, (253, 230, 200), (214, 143, 92), [
            ("circle", 180, 300, 110, (255, 250, 240), 0.7),
            ("circle", 420, 560, 150, (190, 110, 70), 0.35),
        ]),
        ("night", 760, 560, (28, 32, 74), (90, 70, 160), [
            ("circle", 620, 120, 60, (250, 245, 220), 0.9),
            ("circle", 180, 220, 4, (255, 255, 255), 1.0),
            ("circle", 260, 380, 3, (255, 255, 255), 1.0),
            ("circle", 420, 180, 3, (255, 255, 255), 1.0),
            ("circle", 520, 420, 4, (255, 255, 255), 1.0),
        ]),
        ("coral", 620, 760, (255, 209, 190), (230, 90, 110), [
            ("rect", 90, 90, 530, 180, (255, 255, 255), 0.28),
            ("rect", 90, 260, 530, 350, (255, 255, 255), 0.2),
            ("rect", 90, 430, 530, 520, (255, 255, 255), 0.14),
        ]),
        ("forest", 700, 540, (196, 227, 160), (33, 92, 60), [
            ("circle", 210, 270, 140, (240, 250, 220), 0.22),
            ("circle", 500, 360, 110, (20, 60, 40), 0.4),
        ]),
        ("berry", 580, 700, (243, 167, 199), (120, 42, 112), [
            ("circle", 290, 250, 150, (255, 235, 245), 0.3),
            ("circle", 170, 520, 90, (90, 30, 90), 0.45),
        ]),
        ("peach", 680, 620, (255, 226, 205), (240, 160, 130), [
            ("circle", 340, 310, 200, (255, 250, 245), 0.55),
            ("circle", 340, 310, 120, (250, 190, 160), 0.6),
        ]),
    ]

    created: list[Path] = []
    for name, width, height, top, bottom, shapes in specs:
        canvas = Canvas(width, height, top, bottom)
        for shape in shapes:
            if shape[0] == "circle":
                _, cx, cy, radius, color, alpha = shape
                canvas.circle(cx, cy, radius, color, alpha)
            else:
                _, x0, y0, x1, y1, color, alpha = shape
                canvas.rect(x0, y0, x1, y1, color, alpha)
        path = folder / f"{name}.png"
        canvas.save(path)
        created.append(path)
        print(f"  картинка: {path.name} {width}x{height}")
    return created


# ------------------------------------------------------------------- данные
USERS = [
    ("ksenia", "Ксения Дутикова"),
    ("artem", "Артём Панов"),
]

POSTS = [
    ("ksenia", "sunset", "Закат на набережной — наконец-то поймала этот свет"),
    ("artem", "sea", "Море в четверг. Ни одного человека на горизонте"),
    ("ksenia", "berry", "Ягодный сезон открыт"),
    ("artem", "forest", "Лес после дождя пахнет совершенно иначе"),
    ("ksenia", "peach", "Мягкое утро"),
    ("artem", "night", "Ночное небо без городской засветки"),
]

# (индекс публикации, автор, текст)
COMMENTS = [
    (0, "artem", "Какой свет! В субботу пойдём ещё?"),
    (1, "ksenia", "Кадр получился очень спокойным"),
    (1, "artem", "Спасибо! Снимал на телефон"),
    (3, "ksenia", "Обязательно, только рано утром"),
    (5, "ksenia", "Наконец-то видно звёзды, а не фонари"),
]

DIALOGS = [
    ("ksenia", "artem", "Привет! Твоя фотография моря — просто огонь", 0),
    ("artem", "ksenia", "Спасибо! Снято на телефон, если честно", 1),
    ("ksenia", "artem", "Тем более впечатляет. Пойдёшь в субботу снимать закат?", 0),
    ("artem", "ksenia", "Обязательно. Захвачу штатив", 1),
]


def backup_database(db_path: Path) -> Path | None:
    """Сохраняет старую базу рядом, ничего не удаляя.

    Перед копированием выполняется контрольная точка WAL, чтобы все
    зафиксированные данные попали в основной файл, а не остались
    в mosaic.db-wal.
    """
    if not db_path.exists():
        return None
    try:
        connection = sqlite3.connect(str(db_path))
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
    except sqlite3.Error:
        pass

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}-backup-{stamp}.db")
    counter = 1
    while backup.exists():
        backup = db_path.with_name(
            f"{db_path.stem}-backup-{stamp}-{counter}.db")
        counter += 1
    db_path.replace(backup)
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            try:
                side.unlink()
            except OSError:
                pass
    return backup


def seed(reset: bool = False) -> None:
    config = load_config([]).ensure_dirs()
    if reset and config.db_path.exists():
        try:
            backup = backup_database(config.db_path)
        except PermissionError:
            raise SystemExit(
                "Не удалось сохранить резервную копию базы: файл занят. "
                "Остановите сервер (Ctrl+C) и повторите.")
        if backup is not None:
            print(f"Старая база сохранена: {backup.name}")
            print("Вернуть её можно, переименовав файл обратно в "
                  f"{config.db_path.name} при остановленном сервере.")

    app = Application(config)
    try:
        images_dir = config.uploads_dir / "_demo"
        print("Готовим изображения:")
        images = make_images(images_dir)

        users: dict[str, int] = {}
        for username, display_name in USERS:
            existing = app.repo.get_user_by_username(username)
            if existing:
                users[username] = existing["id"]
                print(f"  пользователь {username} уже есть")
                continue
            salt, digest = hash_password("secret123")
            created = app.repo.create_user(username, display_name, salt, digest,
                                           iso_now())
            users[username] = created["id"]
            print(f"  пользователь {username} создан (пароль secret123)")

        existing_posts = app.repo.count_posts()
        if existing_posts:
            print(f"В базе уже {existing_posts} публикаций, пропускаем загрузку")
        else:
            post_ids: list[int] = []
            for index, (author, image_name, caption) in enumerate(POSTS):
                source = images_dir / f"{image_name}.png"
                filename = app.storage.save(source.read_bytes(), "png")
                post_id = app.repo.create_post(users[author], filename, caption,
                                               iso_now())
                post_ids.append(post_id)
                # Детерминированные лайки: второй пользователь ставит лайк.
                for offset, (liker, _) in enumerate(USERS):
                    if (index + offset) % 2 == 0 and liker != author:
                        app.repo.toggle_like(post_id, users[liker])
                print(f"  публикация #{post_id}: {image_name} — {author}")

            for index, author, text in COMMENTS:
                app.repo.create_comment(post_ids[index], users[author], text,
                                        iso_now())
                print(f"  комментарий к #{post_ids[index]} от {author}")

        if not app.repo.list_dialogs(users["ksenia"]):
            for sender, recipient, text, read in DIALOGS:
                message = app.repo.create_message(
                    users[sender], users[recipient], text, iso_now())
                if read:
                    app.repo.mark_read(users[recipient], users[sender])
                print(f"  сообщение #{message['id']}: {sender} → {recipient}")
        else:
            print("Переписка уже есть, пропускаем")

        print("\nГотово. Аккаунты: "
              + ", ".join(f"{name}/secret123" for name, _ in USERS))
        print(f"Публикаций: {app.repo.count_posts()}")
    finally:
        app.close()


def main() -> int:
    # Русский текст в консоли Windows требует явного UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="Демо-данные «Мозаики»")
    parser.add_argument("--reset", action="store_true",
                        help="сохранить копию базы и создать демо-данные заново")
    arguments = parser.parse_args()
    seed(arguments.reset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
