"""Поиск пользователей и публикаций.

Маршрут ``/api/users`` оставлен для поиска только людей, а
``/api/search`` возвращает два списка: людей и публикации, найденные
по подписи. Оба поиска нечувствительны к регистру, включая кириллицу.
"""

from __future__ import annotations

from typing import Any

from ..core.security import ValidationError, clean_text
from ..http.request import HTTPError, Request
from ..http.response import Response
from ..http.router import Router
from .posts import serialize_post

SEARCH_LIMIT = 10


def _query(request: Request) -> str:
    """Извлекает и нормализует поисковый запрос.

    Args:
        request: GET с параметром ``q``.

    Returns:
        Обрезанная строка не длиннее 40 символов (может быть пустой).

    Raises:
        HTTPError: 400 при некорректном значении.
    """
    raw = request.query_one("q", "") or ""
    try:
        return clean_text(raw, field="запрос", max_length=40,
                          allow_empty=True)
    except ValidationError:
        raise HTTPError(400, "Некорректный поисковый запрос")


def _users(ctx: Any, query: str, exclude_id: int) -> list[dict[str, Any]]:
    """Ищет людей по логину и имени, исключая самого пользователя.

    Args:
        ctx: Контекст с репозиторием.
        query: Строка поиска.
        exclude_id: id текущего пользователя.

    Returns:
        Список словарей ``id``, ``username``, ``display_name``.
    """
    rows = ctx.repo.search_users(query, exclude_id, SEARCH_LIMIT)
    return [{"id": row["id"], "username": row["username"],
             "display_name": row["display_name"]} for row in rows]


def handle_search(request: Request, params: dict[str, str],
                  ctx: Any, user: dict) -> Response:
    """Ищет только пользователей (совместимый маршрут).

    Args:
        request: GET ``/api/users?q=...``.
        params: Параметры пути (не используются).
        ctx: Контекст приложения.
        user: Текущий пользователь.

    Returns:
        200 с полем ``users``.
    """
    query = _query(request)
    if not query:
        return Response.json({"users": []})
    return Response.json({"users": _users(ctx, query, user["id"])})


def handle_search_all(request: Request, params: dict[str, str],
                      ctx: Any, user: dict) -> Response:
    """Ищет людей и публикации по подписям.

    Args:
        request: GET ``/api/search?q=...``.
        params: Параметры пути (не используются).
        ctx: Контекст приложения.
        user: Текущий пользователь.

    Returns:
        200 с полями ``users`` и ``posts``.
    """
    query = _query(request)
    if not query:
        return Response.json({"users": [], "posts": []})
    posts = ctx.repo.search_posts(query, user["id"], SEARCH_LIMIT)
    return Response.json({
        "users": _users(ctx, query, user["id"]),
        "posts": [serialize_post(row) for row in posts],
    })


def register_routes(router: Router) -> None:
    """Добавляет маршруты поиска в общую таблицу.

    Args:
        router: Таблица маршрутов приложения.
    """
    router.add("GET", "/api/users", handle_search)
    router.add("GET", "/api/search", handle_search_all)
