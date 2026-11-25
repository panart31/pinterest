"""Личные сообщения: диалоги, отправка, отметка о прочтении.

Сообщения хранятся в таблице ``messages`` и привязаны к двум
пользователям. Клиент обновляет открытый диалог опросом раз в три
секунды, передавая ``after_id`` — идентификатор последнего известного
сообщения. Тексты в журнал аудита не попадают, только идентификаторы.
"""

from __future__ import annotations

from typing import Any

from ..core.audit import audit_event
from ..core.clock import iso_now
from ..core.security import ValidationError, validate_message
from ..http.request import HTTPError, Request
from ..http.response import Response
from ..http.router import Router

MAX_AFTER_ID = 10 ** 9


def _recipient(ctx: Any, username: str) -> dict[str, Any]:
    """Находит собеседника по логину.

    Args:
        ctx: Контекст с репозиторием.
        username: Логин из пути.

    Returns:
        Строка пользователя.

    Raises:
        HTTPError: 404, если пользователя нет.
    """
    row = ctx.repo.get_user_by_username(username)
    if row is None:
        raise HTTPError(404, "Пользователь не найден")
    return row


def serialize_message(row: dict[str, Any], viewer_id: int) -> dict[str, Any]:
    """Превращает строку сообщения в объект API.

    Args:
        row: Строка из таблицы messages.
        viewer_id: id текущего пользователя (для поля ``mine``).

    Returns:
        Словарь с id, текстом, временем, участниками и признаком «моё».
    """
    return {
        "id": row["id"],
        "text": row["text"],
        "created_at": row["created_at"],
        "sender_id": row["sender_id"],
        "recipient_id": row["recipient_id"],
        "mine": row["sender_id"] == viewer_id,
        "is_read": bool(row["is_read"]),
    }


def handle_dialogs(request: Request, params: dict[str, str],
                   ctx: Any, user: dict) -> Response:
    """Отдаёт список диалогов с последним сообщением и непрочитанными.

    Args:
        request: GET с cookie.
        params: Параметры пути (не используются).
        ctx: Контекст с репозиторием.
        user: Текущий пользователь.

    Returns:
        200 с полями ``dialogs`` и ``unread_total``.
    """
    rows = ctx.repo.list_dialogs(user["id"])
    dialogs = []
    for row in rows:
        dialogs.append({
            "user": {
                "id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
            },
            "last_text": row["last_text"],
            "last_at": row["last_at"],
            "last_mine": row["last_sender_id"] == user["id"],
            "unread": row["unread"],
        })
    return Response.json({"dialogs": dialogs,
                          "unread_total": ctx.repo.unread_total(user["id"])})


def handle_dialog(request: Request, params: dict[str, str],
                  ctx: Any, user: dict) -> Response:
    """Отдаёт переписку с одним пользователем.

    Параметр ``after_id`` позволяет получить только новые сообщения
    при опросе.

    Args:
        request: GET с необязательным ``after_id``.
        params: Параметры пути с логином собеседника.
        ctx: Контекст с репозиторием.
        user: Текущий пользователь.

    Returns:
        200 с полями ``user``, ``messages`` и ``unread_total``.

    Raises:
        HTTPError: 400 при диалоге с собой, 404 если собеседника нет.
    """
    other = _recipient(ctx, params.get("username", ""))
    if other["id"] == user["id"]:
        raise HTTPError(400, "Нельзя открыть диалог с самим собой")

    raw_after = request.query_one("after_id", "0")
    try:
        after_id = max(0, int(raw_after))
    except (TypeError, ValueError):
        raise HTTPError(400, "after_id должен быть числом")

    rows = ctx.repo.list_dialog(user["id"], other["id"], after_id)
    return Response.json({
        "user": {"id": other["id"], "username": other["username"],
                 "display_name": other["display_name"]},
        "messages": [serialize_message(row, user["id"]) for row in rows],
        "unread_total": ctx.repo.unread_total(user["id"]),
    })


def handle_send(request: Request, params: dict[str, str],
                ctx: Any, user: dict) -> Response:
    """Отправляет личное сообщение.

    Args:
        request: POST с JSON ``{"text": "..."}``.
        params: Параметры пути с логином получателя.
        ctx: Контекст с репозиторием.
        user: Отправитель.

    Returns:
        201 с объектом ``message``.

    Raises:
        HTTPError: 400 при пустом тексте или отправке себе, 404 если
            получателя нет.
    """
    other = _recipient(ctx, params.get("username", ""))
    if other["id"] == user["id"]:
        raise HTTPError(400, "Нельзя отправить сообщение самому себе")

    payload = request.json_body()
    try:
        text = validate_message(payload.get("text"))
    except ValidationError as exc:
        raise HTTPError(400, str(exc))

    created = ctx.repo.create_message(user["id"], other["id"], text, iso_now())
    audit_event("message", user=user["username"], ip=request.remote_addr,
                to=other["username"], message_id=created["id"],
                length=len(text))
    return Response.json({"message": serialize_message(created, user["id"])},
                         status=201)


def handle_read(request: Request, params: dict[str, str],
                ctx: Any, user: dict) -> Response:
    """Помечает входящие сообщения от собеседника прочитанными.

    Args:
        request: POST без тела.
        params: Параметры пути с логином собеседника.
        ctx: Контекст с репозиторием.
        user: Читающий пользователь.

    Returns:
        200 с числом обновлённых сообщений и общим счётчиком.
    """
    other = _recipient(ctx, params.get("username", ""))
    updated = ctx.repo.mark_read(user["id"], other["id"])
    audit_event("messages_read", user=user["username"],
                ip=request.remote_addr, peer=other["username"],
                updated=updated)
    return Response.json({"updated": updated,
                          "unread_total": ctx.repo.unread_total(user["id"])})


def register_routes(router: Router) -> None:
    """Добавляет маршруты сообщений в общую таблицу.

    Args:
        router: Таблица маршрутов приложения.
    """
    router.add("GET", "/api/messages", handle_dialogs)
    router.add("GET", "/api/messages/{username}", handle_dialog)
    router.add("POST", "/api/messages/{username}", handle_send)
    router.add("POST", "/api/messages/{username}/read", handle_read)
