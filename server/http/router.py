"""Маршрутизация: сопоставление метода и пути с обработчиком.

Шаблон пути состоит из сегментов; сегмент в фигурных скобках является
параметром и передаётся обработчику словарём. Если путь совпал, а метод
нет, выбрасывается ``MethodNotAllowed`` (ответ 405 с Allow), если не
совпал путь — ``NotFound`` (404).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class NotFound(Exception):
    """Маршрут не найден."""


class MethodNotAllowed(Exception):
    """Путь существует, но метод не поддерживается.

    Attributes:
        allowed: Список допустимых методов для заголовка Allow.
    """

    def __init__(self, allowed: list[str]):
        super().__init__("Метод не поддерживается")
        self.allowed = allowed


@dataclass(frozen=True)
class Route:
    """Один маршрут таблицы.

    Attributes:
        method: HTTP-метод (GET или POST).
        pattern: Исходный шаблон, например ``/api/posts/{post_id}/like``.
        segments: Разбитый на сегменты шаблон.
        handler: Функция ``handler(request, params, ctx, user)``.
        auth: Требуется ли активная сессия.
        meta: Дополнительные сведения (зарезервировано).
    """

    method: str
    pattern: str
    segments: tuple[str, ...]
    handler: Callable[..., Any]
    auth: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


def _split_path(path: str) -> tuple[str, ...]:
    """Делит путь на непустые сегменты.

    Args:
        path: Путь вида ``/api/posts/5``.

    Returns:
        Кортеж сегментов без пустых строк.
    """
    return tuple(part for part in path.split("/") if part)


def _match(pattern: tuple[str, ...],
           parts: tuple[str, ...]) -> dict[str, str] | None:
    """Сопоставляет шаблон с сегментами пути.

    Args:
        pattern: Сегменты шаблона (могут содержать ``{name}``).
        parts: Сегменты фактического пути.

    Returns:
        Словарь параметров или None, если пути не совпали.
    """
    if len(pattern) != len(parts):
        return None
    params: dict[str, str] = {}
    for expected, actual in zip(pattern, parts):
        if expected.startswith("{") and expected.endswith("}"):
            params[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return params


class Router:
    """Таблица маршрутов с поддержкой параметров вида ``{name}``."""

    def __init__(self) -> None:
        """Создаёт пустую таблицу маршрутов."""
        self._routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Callable[..., Any],
            *, auth: bool = True, **meta: Any) -> None:
        """Добавляет маршрут.

        Args:
            method: HTTP-метод (регистр не важен).
            pattern: Шаблон пути.
            handler: Обработчик с сигнатурой ``(request, params, ctx, user)``.
            auth: Требовать ли сессию (по умолчанию да).
            **meta: Дополнительные сведения о маршруте.
        """
        self._routes.append(Route(
            method=method.upper(),
            pattern=pattern,
            segments=_split_path(pattern),
            handler=handler,
            auth=auth,
            meta=meta,
        ))

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str]]:
        """Ищет маршрут по методу и пути.

        Args:
            method: HTTP-метод запроса.
            path: Путь без query string.

        Returns:
            Пару «маршрут, параметры пути».

        Raises:
            MethodNotAllowed: путь найден, но метод другой.
            NotFound: ни один шаблон не совпал.
        """
        parts = _split_path(path)
        allowed: set[str] = set()
        for route in self._routes:
            params = _match(route.segments, parts)
            if params is None:
                continue
            if route.method == method.upper():
                return route, params
            allowed.add(route.method)
        if allowed:
            raise MethodNotAllowed(sorted(allowed))
        raise NotFound(path)

    def routes(self) -> list[Route]:
        """Возвращает копию списка маршрутов.

        Returns:
            Список Route (для документации и тестов).
        """
        return list(self._routes)
