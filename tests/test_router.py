"""Юнит-тесты маршрутизатора: параметры, 404 и 405."""

from __future__ import annotations

import pytest

from server.http.router import MethodNotAllowed, NotFound, Router


def sample_router() -> Router:
    router = Router()
    router.add("GET", "/api/feed", lambda *a: "feed")
    router.add("POST", "/api/posts", lambda *a: "create")
    router.add("POST", "/api/posts/{post_id}/like", lambda *a: "like")
    router.add("GET", "/uploads/{name}", lambda *a: "file", auth=False)
    return router


def test_static_route_matches():
    route, params = sample_router().match("GET", "/api/feed")
    assert params == {}
    assert route.pattern == "/api/feed"


def test_parameter_captured():
    route, params = sample_router().match("POST", "/api/posts/42/like")
    assert params == {"post_id": "42"}
    assert route.handler(None, params) == "like"


def test_unknown_path_gives_404():
    with pytest.raises(NotFound):
        sample_router().match("GET", "/api/unknown")


def test_wrong_method_gives_405_with_allow():
    with pytest.raises(MethodNotAllowed) as error:
        sample_router().match("GET", "/api/posts")
    assert error.value.allowed == ["POST"]


def test_trailing_slash_is_ignored():
    route, _ = sample_router().match("GET", "/api/feed/")
    assert route.pattern == "/api/feed"
