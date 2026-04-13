"""Фикстуры pytest для TOOL-manager."""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long!!")

import pytest
import httpx
from httpx import ASGITransport

from app.main import app
from app.deps import require_jwt


@pytest.fixture
async def client():
    """
    AsyncClient к FastAPI-приложению с подменой JWT.
    Вход: Фикстура без параметров; require_jwt подменён на возврат {"sub": "1"}.
    Выход: httpx.AsyncClient с base_url http://test; после теста overrides сброшены.
    """
    async def override_jwt():
        return {"sub": "1"}

    app.dependency_overrides[require_jwt] = override_jwt
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def mock_docker_client(monkeypatch):
    """
    Заглушка для тестов, которые сами патчат docker.
    Вход: monkeypatch (не используется в теле).
    Выход: None; тесты используют @patch на docker.from_env и т.п.
    """
    return None
