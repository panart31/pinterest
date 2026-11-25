"""Лента, публикации, лайки, комментарии и скачивание.

Модуль реализует маршруты ``/api/feed``, ``/api/posts`` и вложенные
операции над публикацией. Все изменяющие операции требуют сессии,
а удаление доступно только автору.
"""

from __future__ import annotations

from typing import Any

from ..core.audit import audit_event
from ..core.clock import iso_now
from ..core.security import (
    ValidationError,
    detect_image_extension,
    validate_caption,
    validate_comment,
)
from ..http.multipart import MultipartError, find_part, parse_multipart
from ..http.request import HTTPError, Request
from ..http.response import Response
from ..http.router import Router

DEFAULT_LIMIT = 12
MAX_LIMIT = 50


def serialize_post(row: dict[str, Any]) -> dict[str, Any]:
    """Превращает строку SQL в карточку ленты.

    Args:
        row: Результат запроса с полями публикации, автора и счётчиками.

    Returns:
        Словарь с id, подписью, ссылкой на файл, автором, лайками,
        признаком лайка, числом комментариев и временем создания.
    """
    return {
        "id": row["id"],
        "caption": row["caption"],
        "image_url": f"/uploads/{row['filename']}",
        "author": {
            "id": row["author_id"],
            "username": row["author_username"],
            "display_name": row["author_display_name"],
        },
        "likes": row["likes"],
        "liked": bool(row["liked"]),
        "comments": row.get("comments", 0),
        "created_at": row["created_at"],
    }


def serialize_comment(row: dict[str, Any]) -> dict[str, Any]:
    """Превращает строку комментария в объект API.

    Args:
        row: Строка с текстом, временем и данными автора.

    Returns:
        Словарь с id, текстом, временем и автором.
    """
    return {
        "id": row["id"],
        "text": row["text"],
        "created_at": row["created_at"],
        "author": {
            "id": row["author_id"],
            "username": row["username"],
            "display_name": row["display_name"],
        },
    }


def _post_id(params: dict[str, str]) -> int:
    """Достаёт числовой id публикации из параметров пути.

    Args:
        params: Параметры маршрута.

    Returns:
        Положительный идентификатор.

    Raises:
        HTTPError: 404, если параметр отсутствует или не число.
    """
    try:
        return int(params["post_id"])
    except (KeyError, ValueError):
        raise HTTPError(404, "Публикация не найдена")


def _int_param(request: Request, name: str, default: int, minimum: int,
               maximum: int) -> int:
    """Читает целочисленный параметр запроса с ограничением диапазона.

    Args:
        request: Запрос с query string.
        name: Имя параметра.
        default: Значение, если параметра нет.
        minimum: Нижняя граница (значения меньше приводятся к ней).
        maximum: Верхняя граница.

    Returns:
        Число в диапазоне [minimum, maximum].

    Raises:
        HTTPError: 400, если параметр не является числом.
    """
    raw = request.query_one(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise HTTPError(400, f"Параметр {name} должен быть числом")
    return max(minimum, min(maximum, value))


def handle_feed(request: Request, params: dict[str, str],
                ctx: Any, user: dict) -> Response:
    """Отдаёт ленту с пагинацией и необязательным фильтром по автору.

    Args:
        request: GET с параметрами limit, offset и, возможно, author.
        params: Параметры пути (не используются).
        ctx: Контекст с репозиторием.
        user: Текущий пользователь (нужен для отметки «лайкнуто мной»).

    Returns:
        200 с полями posts, total, limit, offset.

    Raises:
        HTTPError: 400 при нечисловых параметрах, 404 если автор не найден.
    """
    limit = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int_param(request, "offset", 0, 0, 10 ** 9)

    author = request.query_one("author")
    author_id = None
    author_info = None
    if author:
        author_row = ctx.repo.get_user_by_username(author)
        if author_row is None:
            raise HTTPError(404, "Пользователь не найден")
        author_id = author_row["id"]
        author_info = {"id": author_row["id"], "username": author_row["username"],
                       "display_name": author_row["display_name"]}

    rows = ctx.repo.list_posts(user["id"], limit, offset, author_id)
    body = {
        "posts": [serialize_post(row) for row in rows],
        "total": ctx.repo.count_posts(author_id),
        "limit": limit,
        "offset": offset,
    }
    if author_info is not None:
        body["user"] = author_info
    return Response.json(body)


def handle_create_post(request: Request, params: dict[str, str],
                       ctx: Any, user: dict) -> Response:
    """Принимает изображение и подпись через multipart/form-data.

    Проверяет размер файла и его формат по сигнатуре, сохраняет файл под
    случайным именем и создаёт запись в базе.

    Args:
        request: POST с телом multipart (части image и caption).
        params: Параметры пути (не используются).
        ctx: Контекст с хранилищем, репозиторием и лимитами.
        user: Автор публикации.

    Returns:
        201 с карточкой созданной публикации.

    Raises:
        HTTPError: 400 при неверной форме или формате, 413 при большом файле.
    """
    content_type = request.content_type
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPError(400, "Загрузка возможна только через multipart/form-data")
    try:
        parts = parse_multipart(request.body, content_type)
    except MultipartError as exc:
        raise HTTPError(400, str(exc))

    image = find_part(parts, "image")
    if image is None or not image.filename:
        raise HTTPError(400, "В форме отсутствует файл изображения")
    if not image.data:
        raise HTTPError(400, "Файл изображения пуст")
    if len(image.data) > ctx.config.max_upload:
        raise HTTPError(413, "Размер файла превышает 5 МБ")

    extension = detect_image_extension(image.data)
    if extension is None:
        raise HTTPError(400, "Поддерживаются только JPEG, PNG, GIF и WEBP")

    caption_part = find_part(parts, "caption")
    raw_caption = ""
    if caption_part is not None:
        raw_caption = caption_part.data.decode("utf-8", errors="replace")
    try:
        caption = validate_caption(raw_caption)
    except ValidationError as exc:
        raise HTTPError(400, str(exc))

    filename = ctx.storage.save(image.data, extension)
    post_id = ctx.repo.create_post(user["id"], filename, caption, iso_now())
    row = ctx.repo.get_post(post_id, user["id"])
    audit_event("upload", user=user["username"], ip=request.remote_addr,
                post_id=post_id, bytes=len(image.data), ext=extension)
    return Response.json({"post": serialize_post(row)}, status=201)


def handle_like(request: Request, params: dict[str, str],
                ctx: Any, user: dict) -> Response:
    """Ставит или снимает лайк и возвращает новое состояние.

    Args:
        request: POST без тела.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием.
        user: Пользователь, ставящий лайк.

    Returns:
        200 с полями liked и likes.

    Raises:
        HTTPError: 404, если публикации нет.
    """
    post_id = _post_id(params)
    result = ctx.repo.toggle_like(post_id, user["id"])
    if result is None:
        raise HTTPError(404, "Публикация не найдена")
    liked, total = result
    return Response.json({"liked": liked, "likes": total})


def handle_get_post(request: Request, params: dict[str, str],
                    ctx: Any, user: dict) -> Response:
    """Возвращает полную карточку одной публикации.

    Args:
        request: GET с cookie.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием.
        user: Текущий пользователь.

    Returns:
        200 с объектом ``post``.

    Raises:
        HTTPError: 404, если публикации нет.
    """
    post_id = _post_id(params)
    row = ctx.repo.get_post(post_id, user["id"])
    if row is None:
        raise HTTPError(404, "Публикация не найдена")
    return Response.json({"post": serialize_post(row)})


def handle_comments(request: Request, params: dict[str, str],
                    ctx: Any, user: dict) -> Response:
    """Отдаёт комментарии публикации в хронологическом порядке.

    Args:
        request: GET с cookie.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием.
        user: Текущий пользователь.

    Returns:
        200 с полями comments и total.

    Raises:
        HTTPError: 404, если публикации нет.
    """
    post_id = _post_id(params)
    if ctx.repo.get_post(post_id, user["id"]) is None:
        raise HTTPError(404, "Публикация не найдена")
    rows = ctx.repo.list_comments(post_id)
    return Response.json({
        "comments": [serialize_comment(row) for row in rows],
        "total": len(rows),
    })


def handle_add_comment(request: Request, params: dict[str, str],
                       ctx: Any, user: dict) -> Response:
    """Добавляет комментарий к публикации.

    Args:
        request: POST с JSON ``{"text": "..."}``.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием.
        user: Автор комментария.

    Returns:
        201 с объектом ``comment``.

    Raises:
        HTTPError: 400 при пустом тексте, 404 если публикации нет.
    """
    post_id = _post_id(params)
    payload = request.json_body()
    try:
        text = validate_comment(payload.get("text"))
    except ValidationError as exc:
        raise HTTPError(400, str(exc))
    created = ctx.repo.create_comment(post_id, user["id"], text, iso_now())
    if created is None:
        raise HTTPError(404, "Публикация не найдена")
    row = {
        "id": created["id"],
        "text": created["text"],
        "created_at": created["created_at"],
        "author_id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
    }
    audit_event("comment", user=user["username"], ip=request.remote_addr,
                post_id=post_id, comment_id=created["id"])
    return Response.json({"comment": serialize_comment(row)}, status=201)


def handle_delete_post(request: Request, params: dict[str, str],
                       ctx: Any, user: dict) -> Response:
    """Удаляет свою публикацию вместе с файлом.

    Используется POST, а не DELETE: по условиям работы сервер
    поддерживает только GET и POST. Лайки и комментарии удаляются
    каскадом на уровне базы.

    Args:
        request: POST без тела.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием и хранилищем.
        user: Текущий пользователь (должен быть автором).

    Returns:
        204 без тела.

    Raises:
        HTTPError: 404 если публикации нет, 403 если она чужая.
    """
    post_id = _post_id(params)
    row = ctx.repo.get_post(post_id, user["id"])
    if row is None:
        raise HTTPError(404, "Публикация не найдена")
    if row["author_id"] != user["id"]:
        audit_event("delete_post", user=user["username"],
                    ip=request.remote_addr, post_id=post_id,
                    result="forbidden")
        raise HTTPError(403, "Можно удалять только свои публикации")
    filename = ctx.repo.delete_post(post_id, user["id"])
    if filename:
        ctx.storage.delete(filename)
    audit_event("delete_post", user=user["username"],
                ip=request.remote_addr, post_id=post_id, result="ok")
    return Response.no_content()


def handle_download(request: Request, params: dict[str, str],
                    ctx: Any, user: dict) -> Response:
    """Отдаёт файл публикации как вложение.

    Args:
        request: GET с cookie.
        params: Параметры пути с post_id.
        ctx: Контекст с репозиторием и хранилищем.
        user: Текущий пользователь.

    Returns:
        200 с изображением и заголовком ``Content-Disposition``.

    Raises:
        HTTPError: 404, если публикации или файла нет.
    """
    post_id = _post_id(params)
    row = ctx.repo.get_post(post_id, user["id"])
    if row is None:
        raise HTTPError(404, "Публикация не найдена")
    found = ctx.storage.read(row["filename"])
    if found is None:
        raise HTTPError(404, "Файл не найден")
    data, mime = found
    extension = row["filename"].rsplit(".", 1)[-1]
    response = Response.binary(data, mime)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="mosaic-{post_id}.{extension}"')
    return response


def register_routes(router: Router) -> None:
    """Добавляет маршруты публикаций в общую таблицу.

    Args:
        router: Таблица маршрутов приложения.
    """
    router.add("GET", "/api/feed", handle_feed)
    router.add("POST", "/api/posts", handle_create_post)
    router.add("GET", "/api/posts/{post_id}", handle_get_post)
    router.add("POST", "/api/posts/{post_id}/like", handle_like)
    router.add("GET", "/api/posts/{post_id}/comments", handle_comments)
    router.add("POST", "/api/posts/{post_id}/comments", handle_add_comment)
    router.add("GET", "/api/posts/{post_id}/download", handle_download)
    router.add("POST", "/api/posts/{post_id}/delete", handle_delete_post)
