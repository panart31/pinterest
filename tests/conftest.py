"""Общие фикстуры pytest: временная БД и настоящий TCP-сервер."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import ServerFixture, make_config  # noqa: E402


@pytest.fixture()
def config(tmp_path: Path):
    return make_config(tmp_path)


@pytest.fixture()
def server(config):
    fixture = ServerFixture(config).start()
    try:
        yield fixture
    finally:
        fixture.stop()


@pytest.fixture()
def client(server):
    return server.client()
