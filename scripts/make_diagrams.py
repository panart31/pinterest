#!/usr/bin/env python3
"""Генерация диаграмм для пояснительной записки.

Рисунки строятся средствами matplotlib (без Graphviz и PlantUML),
поэтому скрипт воспроизводим на любой машине с Python.
Результат — PNG 300 dpi в docs/diagrams.

Запуск:
    python scripts/make_diagrams.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "diagrams"

INK = "#1d1a21"
MUTED = "#6f6a75"
ACCENT = "#d6396f"
VIOLET = "#7c5cff"
BLUE = "#3f9be0"
AMBER = "#f2994a"
GREEN = "#2c7a4b"
SOFT = "#fbe7ee"
PAPER = "#ffffff"
LINE = "#b9b2bf"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.unicode_minus": False,
})


# --------------------------------------------------------------- примитивы
def canvas(width: float = 12.0, height: float = 7.5,
           xlim: tuple[float, float] = (0, 16),
           ylim: tuple[float, float] = (0, 10)):
    figure, axes = plt.subplots(figsize=(width, height), dpi=300)
    figure.patch.set_facecolor(PAPER)
    axes.set_facecolor(PAPER)
    axes.set_xlim(*xlim)
    axes.set_ylim(*ylim)
    axes.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return figure, axes


def card(ax, cx, cy, w, h, title, lines=(), fc=PAPER, ec=INK,
         title_color=INK, fs=8.6, title_fs=10.2, align="center",
         lw=1.3, radius=0.16, muted_color=MUTED, zorder=3):
    """Прямоугольник с заголовком и строками текста."""
    shadow = FancyBboxPatch(
        (cx - w / 2 + 0.05, cy - h / 2 - 0.07), w, h,
        boxstyle=f"round,pad=0.01,rounding_size={radius}",
        linewidth=0, facecolor="#00000012", zorder=zorder - 1)
    ax.add_patch(shadow)
    patch = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0.01,rounding_size={radius}",
        linewidth=lw, edgecolor=ec, facecolor=fc, zorder=zorder)
    ax.add_patch(patch)

    top = cy + h / 2 - 0.26
    if align == "left":
        ax.text(cx - w / 2 + 0.22, top, title, ha="left", va="top",
                fontsize=title_fs, fontweight="bold", color=title_color,
                zorder=zorder + 1)
        if lines:
            ax.text(cx - w / 2 + 0.22, top - 0.36, "\n".join(lines),
                    ha="left", va="top", fontsize=fs, color=muted_color,
                    linespacing=1.42, zorder=zorder + 1)
    else:
        ax.text(cx, top, title, ha="center", va="top",
                fontsize=title_fs, fontweight="bold", color=title_color,
                zorder=zorder + 1)
        if lines:
            ax.text(cx, top - 0.34, "\n".join(lines), ha="center", va="top",
                    fontsize=fs, color=muted_color, linespacing=1.45,
                    zorder=zorder + 1)


def arrow(ax, start, end, label=None, color=MUTED, lw=1.5, rad=0.0,
          style="-|>", fs=8.4, label_offset=(0, 0.22), dashed=False,
          zorder=2):
    patch = FancyArrowPatch(
        start, end, arrowstyle=style, mutation_scale=13, linewidth=lw,
        color=color, shrinkA=1, shrinkB=1, zorder=zorder,
        linestyle="--" if dashed else "-",
        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(patch)
    if label:
        mx = (start[0] + end[0]) / 2 + label_offset[0]
        my = (start[1] + end[1]) / 2 + label_offset[1]
        ax.text(mx, my, label, ha="center", va="bottom", fontsize=fs,
                color=color, zorder=zorder + 1)


def diamond(ax, cx, cy, w, h, text, fc=PAPER, ec=INK, fs=8.4):
    points = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2),
              (cx - w / 2, cy)]
    ax.add_patch(Polygon(points, closed=True, facecolor=fc, edgecolor=ec,
                         linewidth=1.3, zorder=3))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs,
            color=INK, zorder=4, linespacing=1.3)


def title(ax, text, subtitle=None):
    ax.text(0.35, 9.62, text, ha="left", va="top", fontsize=15,
            fontweight="bold", color=INK)
    if subtitle:
        ax.text(0.37, 9.08, subtitle, ha="left", va="top", fontsize=9.5,
                color=MUTED)


def save(figure, name):
    path = OUTPUT / name
    figure.savefig(path, dpi=300, facecolor=PAPER)
    plt.close(figure)
    print(f"  {path.name}")


# ------------------------------------------------------- 1. схема взаимодействия
def diagram_interaction():
    figure, ax = canvas()
    title(ax, "Схема взаимодействия",
          "Сервер и клиент — два ноутбука в одной локальной сети")

    card(ax, 3.6, 5.9, 5.4, 3.8,
         "Ноутбук 1 — сервер",
         ["server/main.py --host 0.0.0.0 --port 8000",
          "HTTP/1.1 на TCP-сокетах",
          "SQLite: storage/mosaic.db",
          "Файлы: storage/uploads",
          "Журнал: консоль + server.log"],
         fc="#fff5f8", ec=ACCENT, title_color=ACCENT, fs=8.8)

    card(ax, 12.4, 5.9, 5.4, 3.8,
         "Ноутбук 2 — клиент",
         ["Браузер: SPA (HTML, CSS, JS)",
          "client_raw.py — клиент на сокетах",
          "Wireshark — анализ трафика",
          "http://192.168.0.10:8000"],
         fc="#f4f1ff", ec=VIOLET, title_color=VIOLET, fs=8.8)

    arrow(ax, (9.68, 6.75), (6.32, 6.75), "HTTP-запрос (GET /api/feed HTTP/1.1)",
          color=ACCENT, lw=1.8, label_offset=(0, 0.16))
    arrow(ax, (6.32, 5.0), (9.68, 5.0), "HTTP-ответ (200 OK, JSON)",
          color=VIOLET, lw=1.8, label_offset=(0, -0.42))

    ax.text(8.0, 5.85, "TCP\nпорт 8000", ha="center", va="center",
            fontsize=9.5, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=PAPER,
                      edgecolor=LINE, linewidth=1.0))

    band = FancyBboxPatch((0.7, 1.0), 14.6, 1.1,
                          boxstyle="round,pad=0.02,rounding_size=0.18",
                          linewidth=1.2, edgecolor=LINE, facecolor="#faf8fa",
                          linestyle="--")
    ax.add_patch(band)
    ax.text(8.0, 1.55, "Локальная сеть: Wi-Fi, точка доступа телефона или кабель",
            ha="center", va="center", fontsize=9.5, color=MUTED)
    save(figure, "01_interaction.png")


# ------------------------------------------------------- 2. компоненты сервера
def diagram_components():
    figure, ax = canvas(height=8.2)
    title(ax, "Компонентная схема сервера",
          "Запрос проходит слои сверху вниз, ответ — обратно")

    layers = [
        ("TCP-сокет", "core/server.py: accept, recv, sendall, поток на соединение", ACCENT, "#fff5f8"),
        ("HTTP-парсер", "http/request.py · http/response.py · http/multipart.py", AMBER, "#fff8ef"),
        ("Маршрутизатор", "http/router.py: метод + шаблон пути → обработчик", BLUE, "#eff8ff"),
        ("Обработчики API", "api/auth.py · posts.py · users.py · messages.py", VIOLET, "#f4f1ff"),
        ("Репозиторий", "db/repository.py: параметризованные SQL-запросы", GREEN, "#eef8f1"),
    ]
    y = 8.15
    for name, description, color, fill in layers:
        card(ax, 6.0, y, 9.2, 1.18, name, [description],
             fc=fill, ec=color, title_color=color, fs=8.4, title_fs=10)
        y -= 1.55

    # Нижний уровень: два хранилища.
    card(ax, 3.6, 0.55, 4.2, 0.85, "SQLite", ["db/database.py"],
         fc="#eef8f1", ec=GREEN, title_color=GREEN, title_fs=9.2, fs=8.0)
    card(ax, 8.4, 0.55, 4.2, 0.85, "Файловое хранилище", ["core/storage.py"],
         fc="#eef8f1", ec=GREEN, title_color=GREEN, title_fs=9.2, fs=8.0)

    # Вертикальные стрелки между слоями (строго в зазорах).
    arrow(ax, (6.0, 7.56), (6.0, 7.19), color=MUTED)
    arrow(ax, (6.0, 6.01), (6.0, 5.64), color=MUTED)
    arrow(ax, (6.0, 4.46), (6.0, 4.09), color=MUTED)
    arrow(ax, (6.0, 2.91), (6.0, 2.54), color=MUTED)
    arrow(ax, (5.4, 1.36), (3.9, 1.02), color=MUTED)
    arrow(ax, (6.6, 1.36), (7.4, 1.02), color=MUTED)

    # Боковые модули.
    card(ax, 13.4, 4.55, 4.4, 1.15, "Сессии",
         ["core/sessions.py", "токен → пользователь"],
         fc="#fdf6ff", ec=VIOLET, title_color=VIOLET, title_fs=9.4, fs=8.0)
    card(ax, 13.4, 2.55, 4.4, 1.5, "Безопасность",
         ["core/security.py: PBKDF2,", "валидация, safe_join,", "проверка сигнатур"],
         fc="#fdf6ff", ec=VIOLET, title_color=VIOLET, title_fs=9.4, fs=8.0)

    arrow(ax, (11.15, 4.45), (10.65, 3.85), color=VIOLET, style="<|-|>",
          rad=-0.1)
    arrow(ax, (11.15, 2.85), (10.65, 3.2), color=VIOLET, style="<|-|>",
          rad=0.1)
    save(figure, "02_components.png")


# ------------------------------------------------------- 3. классы
def diagram_classes():
    figure, ax = canvas(height=8.4)
    title(ax, "Диаграмма классов основных модулей",
          "Показаны только значимые поля и методы")

    card(ax, 2.7, 7.75, 4.4, 2.2, "HTTPServer",
         ["- config: Config",
          "- _socket: socket",
          "+ start()",
          "+ serve_forever()",
          "+ shutdown()"],
         align="left", fc="#fff5f8", ec=ACCENT, title_color=ACCENT, fs=7.9)

    card(ax, 7.9, 7.75, 4.8, 2.2, "Application",
         ["- router: Router",
          "- repo: Repository",
          "- sessions: SessionManager",
          "- storage: Storage",
          "+ dispatch(request)"],
         align="left", fc="#f4f1ff", ec=VIOLET, title_color=VIOLET, fs=7.9)

    card(ax, 13.3, 7.75, 4.2, 2.2, "Router",
         ["- _routes: list[Route]",
          "+ add(method, pattern)",
          "+ match(method, path)"],
         align="left", fc="#eff8ff", ec=BLUE, title_color=BLUE, fs=7.9)

    card(ax, 2.2, 4.5, 3.6, 2.2, "Request",
         ["+ method: str",
          "+ path: str",
          "+ query: dict",
          "+ body: bytes",
          "+ json_body()"],
         align="left", fc="#fff8ef", ec=AMBER, title_color=AMBER, fs=7.9)

    card(ax, 5.9, 4.5, 3.4, 2.2, "Response",
         ["+ status: int",
          "+ headers: dict",
          "+ body: bytes",
          "+ set_cookie()",
          "+ send(socket)"],
         align="left", fc="#fff8ef", ec=AMBER, title_color=AMBER, fs=7.9)

    card(ax, 10.6, 4.5, 3.9, 2.2, "SessionManager",
         ["- repository",
          "+ create(user_id)",
          "+ resolve(token)",
          "+ destroy(token)"],
         align="left", fc="#fdf6ff", ec=VIOLET, title_color=VIOLET, fs=7.9)

    card(ax, 14.3, 4.5, 2.8, 2.2, "Storage",
         ["- root: Path",
          "+ save(data, ext)",
          "+ read(name)"],
         align="left", fc="#eef8f1", ec=GREEN, title_color=GREEN, fs=7.9)

    card(ax, 7.6, 1.25, 4.4, 1.6, "Repository",
         ["+ list_posts(...)",
          "+ create_message(...)",
          "+ toggle_like(...)"],
         align="left", fc="#eef8f1", ec=GREEN, title_color=GREEN, fs=7.9)

    card(ax, 12.6, 1.25, 3.4, 1.6, "Database",
         ["+ connection()",
          "+ init_schema()"],
         align="left", fc="#eef8f1", ec=GREEN, title_color=GREEN, fs=7.9)

    arrow(ax, (4.92, 7.75), (5.45, 7.75), color=MUTED)
    ax.text(5.18, 7.95, "использует", ha="center", va="bottom",
            fontsize=7.6, color=MUTED)
    arrow(ax, (10.32, 7.75), (11.15, 7.75), color=MUTED)
    ax.text(10.73, 7.95, "маршруты", ha="center", va="bottom",
            fontsize=7.6, color=MUTED)

    arrow(ax, (6.5, 6.68), (2.7, 5.62), color=MUTED, rad=0.05)
    ax.text(4.35, 6.25, "создаёт", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)
    arrow(ax, (7.3, 6.65), (6.3, 5.62), color=MUTED)
    arrow(ax, (9.0, 6.68), (10.0, 5.62), color=MUTED)
    arrow(ax, (10.0, 6.72), (13.5, 5.65), color=MUTED, rad=-0.08)

    # Зависимость Application → Repository идёт в зазоре между
    # Response и SessionManager, не пересекая другие классы.
    arrow(ax, (8.2, 6.65), (8.2, 2.07), color=MUTED)
    ax.text(8.05, 2.9, "БД", ha="right", va="center", fontsize=7.6,
            color=MUTED)

    arrow(ax, (9.82, 1.25), (10.88, 1.25), color=MUTED)
    ax.text(10.35, 1.45, "SQL", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)
    save(figure, "03_classes.png")


# ------------------------------------------------------- 4. ER
def diagram_er():
    figure, ax = canvas(height=8.2)
    title(ax, "Схема базы данных (ER)",
          "Шесть таблиц, внешние ключи и каскадное удаление")

    def entity(cx, cy, w, h, name, fields, color):
        card(ax, cx, cy, w, h, name, fields, align="left", fc=PAPER,
             ec=color, title_color=color, fs=7.6, title_fs=9.4)

    entity(2.8, 6.7, 4.6, 2.4, "users", [
        "PK  id            INTEGER",
        "     username      TEXT UNIQUE",
        "     display_name  TEXT",
        "     password_hash TEXT",
        "     salt          TEXT",
        "     created_at    TEXT",
    ], VIOLET)

    entity(8.4, 6.8, 4.6, 2.2, "posts", [
        "PK  id         INTEGER",
        "FK  user_id    → users.id",
        "     filename   TEXT",
        "     caption    TEXT",
        "     created_at TEXT",
    ], ACCENT)

    entity(13.7, 7.15, 3.8, 1.5, "likes", [
        "PK  post_id → posts.id",
        "PK  user_id → users.id",
    ], AMBER)

    entity(2.8, 3.2, 4.6, 1.6, "sessions", [
        "PK  token      TEXT",
        "FK  user_id    → users.id",
        "     expires_at TEXT",
    ], BLUE)

    entity(9.4, 2.45, 8.6, 2.2, "messages", [
        "PK  id           INTEGER",
        "FK  sender_id    → users.id",
        "FK  recipient_id → users.id",
        "     text         TEXT",
        "     created_at   TEXT",
        "     is_read      INTEGER",
    ], GREEN)

    entity(13.7, 5.35, 3.8, 1.7, "comments", [
        "PK  id         INTEGER",
        "FK  post_id    → posts.id",
        "FK  user_id    → users.id",
        "     text       TEXT",
        "     created_at TEXT",
    ], AMBER)

    # users → posts
    arrow(ax, (5.12, 6.9), (6.08, 6.9), style="-", color=MUTED, lw=1.2)
    ax.text(5.6, 7.02, "1 : ∞", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)
    # posts → likes
    arrow(ax, (10.72, 6.9), (11.78, 6.9), style="-", color=MUTED, lw=1.2)
    ax.text(11.25, 7.02, "1 : ∞", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)
    # users → sessions
    arrow(ax, (2.8, 5.5), (2.8, 4.02), style="-", color=MUTED, lw=1.2)
    ax.text(2.95, 4.76, "1 : ∞", ha="left", va="center", fontsize=7.6,
            color=MUTED)
    # posts → comments
    arrow(ax, (10.72, 6.25), (11.78, 5.85), style="-", color=MUTED, lw=1.2,
          rad=-0.05)
    ax.text(11.2, 6.35, "1 : ∞", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)
    # posts → messages
    arrow(ax, (8.4, 5.7), (8.4, 3.57), style="-", color=MUTED, lw=1.2)
    ax.text(8.55, 4.64, "1 : ∞", ha="left", va="center", fontsize=7.6,
            color=MUTED)
    # users → messages (sender и recipient)
    arrow(ax, (4.9, 5.5), (6.4, 3.57), style="-", color=MUTED, lw=1.2,
          rad=-0.08)
    ax.text(5.3, 4.4, "1 : ∞", ha="center", va="center", fontsize=7.6,
            color=MUTED)
    # users → likes: обход сверху, чтобы не пересекать posts
    ax.plot([2.8, 2.8], [7.9, 8.45], color=MUTED, lw=1.2, zorder=2)
    ax.plot([2.8, 13.7], [8.45, 8.45], color=MUTED, lw=1.2, zorder=2)
    arrow(ax, (13.7, 8.45), (13.7, 7.92), style="-", color=MUTED, lw=1.2)
    ax.text(8.2, 8.55, "1 : ∞", ha="center", va="bottom", fontsize=7.6,
            color=MUTED)

    # Подпись о поведении ключей.
    ax.text(8.0, 0.62,
            "PRAGMA foreign_keys = ON; удаление пользователя каскадно "
            "удаляет его сессии, публикации, лайки и комментарии",
            ha="center", va="center", fontsize=8.4, color=MUTED)
    save(figure, "04_er.png")


# ------------------------------------------------------- 5. последовательность: загрузка
def sequence_frame(ax, lifelines, top=8.3, bottom=0.6):
    positions = {}
    for index, (name, subtitle) in enumerate(lifelines):
        x = 1.3 + index * (13.4 / max(1, len(lifelines) - 1))
        positions[name] = x
        card(ax, x, top, 2.2, 0.95, name, [subtitle],
             fc="#f7f5f8", ec=INK, title_fs=8.8, fs=7.2)
        ax.plot([x, x], [bottom, top - 0.5], color=LINE, lw=1.0,
                linestyle=(0, (4, 4)), zorder=1)
    return positions


def message(ax, x1, x2, y, text, color=MUTED, dashed=False, number=None):
    arrow(ax, (x1, y), (x2, y), color=color, dashed=dashed, lw=1.4)
    prefix = f"{number}. " if number else ""
    ax.text((x1 + x2) / 2, y + 0.13, prefix + text, ha="center", va="bottom",
            fontsize=7.9, color=color)


def diagram_sequence_upload():
    figure, ax = canvas(height=8.6)
    title(ax, "Загрузка изображения",
          "Последовательность вызовов от браузера до файла и записи в БД")

    names = [("Клиент", "браузер"), ("HTTPServer", "core/server.py"),
             ("Multipart", "http/multipart.py"), ("API posts", "api/posts.py"),
             ("Storage", "core/storage.py"), ("SQLite", "repository")]
    x = sequence_frame(ax, names, top=8.3, bottom=0.5)

    y = 7.4
    message(ax, x["Клиент"], x["HTTPServer"],
            y, "POST /api/posts (multipart, до 5 МБ)", ACCENT, number=1)
    y -= 0.75
    message(ax, x["HTTPServer"], x["Multipart"], y, "parse_multipart(body)", number=2)
    y -= 0.65
    message(ax, x["Multipart"], x["HTTPServer"], y, "части image и caption",
            dashed=True, number=3)
    y -= 0.75
    message(ax, x["HTTPServer"], x["API posts"], y, "Request + сессия", number=4)
    y -= 0.8
    message(ax, x["API posts"], x["Storage"], y,
            "detect_image_extension + save()", number=5)
    y -= 0.6
    message(ax, x["Storage"], x["API posts"], y, "uuid.png", dashed=True, number=6)
    y -= 0.75
    message(ax, x["API posts"], x["SQLite"], y, "INSERT INTO posts", number=7)
    y -= 0.6
    message(ax, x["SQLite"], x["API posts"], y, "id = 11", dashed=True, number=8)
    y -= 0.85
    message(ax, x["API posts"], x["HTTPServer"], y, "201 Created {post}",
            color=GREEN, dashed=True, number=9)
    y -= 0.7
    message(ax, x["HTTPServer"], x["Клиент"], y,
            "HTTP/1.1 201 + JSON", color=GREEN, dashed=True, number=10)

    ax.text(8.0, 0.32,
            "Файл сохраняется под случайным именем; исходное имя не используется",
            ha="center", va="center", fontsize=8.4, color=MUTED)
    save(figure, "05_sequence_upload.png")


# ------------------------------------------------------- 6. последовательность: сообщения
def diagram_sequence_messages():
    figure, ax = canvas(height=8.6)
    title(ax, "Обмен личными сообщениями",
          "Отправка, опрос раз в 3 секунды и отметка о прочтении")

    names = [("Клиент А", "Ксения"), ("Сервер", "api/messages.py"),
             ("Клиент Б", "Артём")]
    x = sequence_frame(ax, names, top=8.3, bottom=0.5)

    y = 7.4
    message(ax, x["Клиент А"], x["Сервер"], y,
            "POST /api/messages/artem {text}", ACCENT, number=1)
    y -= 0.75
    message(ax, x["Сервер"], x["Клиент Б"], y,
            "при следующем опросе: unread = 1", dashed=True, number=2)
    y -= 0.8
    message(ax, x["Клиент Б"], x["Сервер"], y,
            "GET /api/messages/ksenia?after_id=41", number=3)
    y -= 0.7
    message(ax, x["Сервер"], x["Клиент Б"], y, "messages: [42]", dashed=True, number=4)
    y -= 0.75
    message(ax, x["Клиент Б"], x["Сервер"], y, "POST .../read", number=5)
    y -= 0.6
    message(ax, x["Сервер"], x["Клиент Б"], y, "updated = 1", dashed=True, number=6)
    y -= 0.8
    message(ax, x["Клиент Б"], x["Сервер"], y,
            "POST /api/messages/ksenia {text}", VIOLET, number=7)
    y -= 0.7
    message(ax, x["Сервер"], x["Клиент А"], y,
            "GET ...?after_id=42 → новый ответ", dashed=True, number=8)

    note = FancyBboxPatch((4.6, 0.55), 6.8, 0.85,
                          boxstyle="round,pad=0.02,rounding_size=0.12",
                          linewidth=1.1, edgecolor=AMBER, facecolor="#fff8ef")
    ax.add_patch(note)
    ax.text(8.0, 0.975, "Опрос идёт, пока открыт диалог; окно скрыто — запросов нет",
            ha="center", va="center", fontsize=8.2, color=INK)
    save(figure, "06_sequence_messages.png")


# ------------------------------------------------------- 7. блок-схема
def diagram_flowchart():
    figure, ax = canvas(height=9.0, xlim=(0, 16), ylim=(0, 12))
    ax.set_ylim(0, 12)
    ax.text(0.35, 11.55, "Обработка HTTP-запроса", ha="left", va="top",
            fontsize=15, fontweight="bold", color=INK)

    def term(cx, cy, text, color):
        ax.add_patch(Ellipse((cx, cy), 2.9, 0.72, facecolor=color,
                             edgecolor=color, linewidth=1.2, zorder=3))
        ax.text(cx, cy, text, ha="center", va="center", fontsize=8.6,
                color="white", fontweight="bold", zorder=4)

    def step(cx, cy, text, color=INK, w=3.6, h=0.66):
        card(ax, cx, cy, w, h, text, fc=PAPER, ec=color, title_color=INK,
             title_fs=8.8)

    def error(cx, cy, text):
        card(ax, cx, cy, 2.7, 0.62, text, fc="#fdeef3", ec=ACCENT,
             title_color=ACCENT, title_fs=8.6)

    main_x = 5.6
    err_x = 12.4

    term(main_x, 10.55, "accept()", INK)
    arrow(ax, (main_x, 10.19), (main_x, 9.72))
    step(main_x, 9.38, "read_request(): строка, заголовки")

    diamond(ax, main_x, 8.35, 3.5, 1.15, "запрос\nкорректен?")
    arrow(ax, (main_x, 9.05), (main_x, 8.92))
    arrow(ax, (main_x + 1.75, 8.35), (err_x - 1.35, 8.35), "нет", color=ACCENT,
          fs=8.2)
    error(err_x, 8.35, "400 Bad Request")
    arrow(ax, (main_x, 7.77), (main_x, 7.45), "да", color=GREEN,
          label_offset=(0.35, 0.0), fs=8.2)

    step(main_x, 7.12, "Content-Length ≤ 6 МБ")
    diamond(ax, main_x, 6.15, 3.2, 1.05, "тело\nв лимите?")
    arrow(ax, (main_x, 6.79), (main_x, 6.68))
    arrow(ax, (main_x + 1.6, 6.15), (err_x - 1.35, 6.15), "нет", color=ACCENT,
          fs=8.2)
    error(err_x, 6.15, "413 Payload Too Large")
    arrow(ax, (main_x, 5.62), (main_x, 5.3), "да", color=GREEN,
          label_offset=(0.35, 0.0), fs=8.2)

    step(main_x, 4.97, "router.match(method, path)")
    diamond(ax, main_x, 4.0, 3.4, 1.05, "маршрут\nнайден?")
    arrow(ax, (main_x, 4.64), (main_x, 4.53))
    arrow(ax, (main_x + 1.7, 4.0), (err_x - 1.35, 4.0), "нет", color=ACCENT,
          fs=8.2)
    error(err_x, 4.0, "404 / 405")
    arrow(ax, (main_x, 3.47), (main_x, 3.15), "да", color=GREEN,
          label_offset=(0.35, 0.0), fs=8.2)

    diamond(ax, main_x, 2.82, 3.6, 1.05, "нужна сессия\nи она есть?")
    arrow(ax, (main_x + 1.8, 2.82), (err_x - 1.35, 2.82), "нет", color=ACCENT,
          fs=8.2)
    error(err_x, 2.82, "401 Unauthorized")
    arrow(ax, (main_x, 2.29), (main_x, 1.97), "да", color=GREEN,
          label_offset=(0.35, 0.0), fs=8.2)

    step(main_x, 1.64, "handler(request, params, ctx, user)")
    arrow(ax, (main_x, 1.31), (main_x, 1.02))
    term(main_x, 0.76, "Response.sendall()", GREEN)

    ax.text(12.4, 1.7, "После ответа:\nзапись в журнал\nи close()",
            ha="center", va="center", fontsize=8.4, color=MUTED,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#faf8fa",
                      edgecolor=LINE))
    arrow(ax, (main_x + 1.5, 1.64), (10.9, 1.7), color=LINE, style="-",
          lw=1.0, dashed=True)
    save(figure, "07_flowchart.png")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    print("Строим диаграммы:")
    diagram_interaction()
    diagram_components()
    diagram_classes()
    diagram_er()
    diagram_sequence_upload()
    diagram_sequence_messages()
    diagram_flowchart()
    print(f"Готово: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
