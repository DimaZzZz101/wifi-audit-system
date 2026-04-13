"""Unit tests: app.api.routes.setup"""
import pytest


@pytest.mark.asyncio
async def test_setup_status_no_users(client):
    """
    GET /api/setup/status при отсутствии пользователей.
    Вход: БД без строк в users (чистая после TRUNCATE).
    Выход: HTTP 200; setup_completed == False.
    """
    r = await client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.json()["setup_completed"] is False


@pytest.mark.asyncio
async def test_setup_status_with_user(client, db_session):
    """
    GET /api/setup/status при наличии пользователя.
    Вход: БД с одним User.
    Выход: HTTP 200; setup_completed == True.
    """
    from app.models.user import User
    from app.core.security import get_password_hash

    db_session.add(User(username="exists", hashed_password=get_password_hash("testpass12"), is_active=True))
    await db_session.commit()

    r = await client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.json()["setup_completed"] is True


@pytest.mark.asyncio
async def test_create_first_user(client, db_session):
    """
    POST /api/setup/create-user - первый пользователь.
    Вход: username и password (не короче 8 символов по схеме).
    Выход: HTTP 201; в JSON есть access_token.
    """
    r = await client.post(
        "/api/setup/create-user",
        json={"username": "admin", "password": "testpass123"},
    )
    assert r.status_code == 201
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_create_first_user_duplicate(client, db_session):
    """
    Второй вызов create-user после успешного первого.
    Вход: Первый POST создаёт пользователя; второй POST с другим username.
    Выход: HTTP 400.
    """
    await client.post(
        "/api/setup/create-user",
        json={"username": "admin", "password": "testpass123"},
    )
    r2 = await client.post(
        "/api/setup/create-user",
        json={"username": "admin2", "password": "testpass123"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_create_first_user_empty_body(client):
    """
    Эндпоинт create-user с пустым телом.
    Вход: POST с json={}.
    Выход: HTTP 422.
    """
    r = await client.post("/api/setup/create-user", json={})
    assert r.status_code == 422
