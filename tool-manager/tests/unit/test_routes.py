"""Unit tests: app.routes (контейнеры и образы)."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_list_containers_authenticated(client):
    """
    GET /containers с заголовком Authorization.
    Вход: Bearer-токен; patch list_containers -> [].
    Выход: HTTP 200.
    """
    with patch(
        "app.routes.container_service.list_containers",
        AsyncMock(return_value=[]),
    ):
        r = await client.get("/containers", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_create_container(client):
    """
    POST /containers - создание контейнера.
    Вход: JSON {"image": "test:1"}; мок create_container с полным ответом.
    Выход: HTTP 201.
    """
    with patch(
        "app.routes.container_service.create_container",
        AsyncMock(
            return_value={
                "id": "id1",
                "short_id": "id1",
                "name": "n",
                "image": "test:1",
                "status": "running",
                "created": "now",
            }
        ),
    ):
        r = await client.post(
            "/containers",
            headers={"Authorization": "Bearer x"},
            json={"image": "test:1"},
        )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_stop_container(client):
    """
    DELETE /containers/{id}.
    Вход: Мок stop_container.
    Выход: HTTP 200.
    """
    with patch(
        "app.routes.container_service.stop_container",
        AsyncMock(return_value={"id": "c1", "stopped": True}),
    ):
        r = await client.delete(
            "/containers/c1",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_list_images(client):
    """
    GET /containers/images.
    Вход: Мок list_images -> [].
    Выход: HTTP 200.
    """
    with patch(
        "app.routes.container_service.list_images",
        AsyncMock(return_value=[]),
    ):
        r = await client.get("/containers/images", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_pull_image(client):
    """
    POST /containers/images/pull.
    Вход: JSON {"image": "test:1"}; мок pull_image.
    Выход: HTTP 200.
    """
    with patch(
        "app.routes.container_service.pull_image",
        AsyncMock(return_value={"pulled": True, "image": "test:1"}),
    ):
        r = await client.post(
            "/containers/images/pull",
            headers={"Authorization": "Bearer x"},
            json={"image": "test:1"},
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_pull_image_no_image(client):
    """
    POST /containers/images/pull без поля image.
    Вход: JSON {}.
    Выход: HTTP 422 (валидация тела).
    """
    r = await client.post(
        "/containers/images/pull",
        headers={"Authorization": "Bearer x"},
        json={},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_jwt_returns_401():
    """
    GET /containers без JWT и без override require_jwt.
    Вход: app.dependency_overrides.clear(); отдельный AsyncClient.
    Выход: HTTP 401 или 403 (нет credentials).
    """
    from app.main import app

    app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/containers")
    assert r.status_code in (401, 403)
