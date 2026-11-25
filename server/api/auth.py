"""Регистрация, вход, выход и текущий пользователь.

Модуль отвечает за создание учётных записей, проверку пароля и выдачу
cookie с токеном сессии. Пароли хранятся только в виде PBKDF2-хеша
с индивидуальной солью; в журнал аудита попадают факты входа и выхода,
но не пароли.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..core.audit import audit_event
from ..core.clock import iso_now
from ..core.security import (
    ValidationError,
    burn_password_time,
    hash_password,
    validate_display_name,
    validate_password,
    validate_username,
    verify_password,
)
from ..core.sessions import COOKIE_NAME
from ..http.request import HTTPError, Request
from ..http.response import Response
from ..http.router import Router


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Оставляет только безопасные поля пользователя.

    Args:
        row: Строка пользователя из базы (может содержать хеш и соль).

    Returns:
        Словарь ``id``, ``username``, ``display_name`` без секретов.
    """
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
    }


def _payload(request: Request) -> dict[str, Any]:
    """Разбирает тело входа/регистрации как JSON или форму.

    Args:
        request: Запрос с телом.

    Returns:
        Словарь полей.

    Raises:
        HTTPError: 400, если тело пустое или имеет неверный формат.
    """
    content_type = request.content_type.lower()
    if content_type.startswith("application/json"):
        return request.json_body()
    if content_type.startswith("application/x-www-form-urlencoded"):
        return request.form_body()
    if request.body.lstrip().startswith(b"{"):
        return request.json_body()
    if not request.body:
        raise HTTPError(400, "Тело запроса пусто")
    return request.form_body()


def handle_register(request: Request, params: dict[str, str],
                    ctx: Any, user: dict | None) -> Response:
    """Создаёт пользователя после валидации полей.

    Args:
        request: POST с JSON или формой (username, password, display_name).
        params: Параметры пути (не используются).
        ctx: Контекст приложения с репозиторием.
        user: Текущий пользователь (для этого маршрута всегда None).

    Returns:
        201 с объектом ``user``.

    Raises:
        HTTPError: 400 при неверных данных, 409 при занятом логине.
    """
    payload = _payload(request)
    try:
        username = validate_username(payload.get("username"))
        password = validate_password(payload.get("password"))
        display_name = validate_display_name(
            payload.get("display_name") or username)
    except ValidationError as exc:
        raise HTTPError(400, str(exc))

    salt, password_hash = hash_password(password)
    try:
        created = ctx.repo.create_user(username, display_name, salt,
                                       password_hash, iso_now())
    except sqlite3.IntegrityError:
        audit_event("register", user=username, ip=request.remote_addr,
                    result="conflict")
        raise HTTPError(409, "Пользователь с таким логином уже существует")
    audit_event("register", user=username, ip=request.remote_addr,
                result="ok", user_id=created["id"])
    return Response.json({"user": created}, status=201)


def handle_login(request: Request, params: dict[str, str],
                 ctx: Any, user: dict | None) -> Response:
    """Проверяет пароль и выдаёт cookie с токеном сессии.

    Время ответа не зависит от того, существует ли логин: для
    несуществующего пользователя всё равно выполняется PBKDF2.

    Args:
        request: POST с JSON или формой (username, password).
        params: Параметры пути (не используются).
        ctx: Контекст с репозиторием и менеджером сессий.
        user: Текущий пользователь (не используется).

    Returns:
        200 с объектом ``user`` и заголовком ``Set-Cookie``.

    Raises:
        HTTPError: 401 при неверной паре логин/пароль.
    """
    payload = _payload(request)
    try:
        username = validate_username(payload.get("username"))
    except ValidationError:
        audit_event("login", user=payload.get("username"),
                    ip=request.remote_addr, result="fail",
                    reason="bad_username")
        raise HTTPError(401, "Неверный логин или пароль")

    password = payload.get("password")
    row = ctx.repo.get_user_by_username(username)
    if row is None:
        # PBKDF2 выполняется и для несуществующего логина — время ответа
        # не выдаёт, зарегистрирован пользователь или нет.
        if isinstance(password, str):
            burn_password_time(password)
        audit_event("login", user=username, ip=request.remote_addr,
                    result="fail", reason="unknown_user")
        raise HTTPError(401, "Неверный логин или пароль")
    if not isinstance(password, str) or not verify_password(
            password, row["salt"], row["password_hash"]):
        audit_event("login", user=username, ip=request.remote_addr,
                    result="fail", reason="bad_password")
        raise HTTPError(401, "Неверный логин или пароль")

    token = ctx.sessions.create(row["id"])
    audit_event("login", user=username, ip=request.remote_addr,
                result="ok")
    response = Response.json({"user": public_user(row)})
    response.set_cookie(COOKIE_NAME, token,
                        max_age=ctx.sessions.ttl_seconds)
    return response


def handle_logout(request: Request, params: dict[str, str],
                  ctx: Any, user: dict | None) -> Response:
    """Удаляет сессию и гасит cookie.

    Args:
        request: POST с cookie сессии.
        params: Параметры пути (не используются).
        ctx: Контекст с менеджером сессий.
        user: Пользователь сессии.

    Returns:
        204 без тела.
    """
    ctx.sessions.destroy(request.cookies.get(COOKIE_NAME))
    audit_event("logout", user=user["username"] if user else None,
                ip=request.remote_addr)
    response = Response.no_content()
    response.delete_cookie(COOKIE_NAME)
    return response


def handle_me(request: Request, params: dict[str, str],
              ctx: Any, user: dict | None) -> Response:
    """Возвращает данные текущего пользователя.

    Args:
        request: GET с cookie.
        params: Параметры пути (не используются).
        ctx: Контекст приложения.
        user: Пользователь сессии (гарантированно не None).

    Returns:
        200 с объектом ``user``.
    """
    return Response.json({"user": user})


def register_routes(router: Router) -> None:
    """Добавляет маршруты модуля в общую таблицу.

    Args:
        router: Таблица маршрутов приложения.
    """
    router.add("POST", "/api/register", handle_register, auth=False)
    router.add("POST", "/api/login", handle_login, auth=False)
    router.add("POST", "/api/logout", handle_logout)
    router.add("GET", "/api/me", handle_me)
