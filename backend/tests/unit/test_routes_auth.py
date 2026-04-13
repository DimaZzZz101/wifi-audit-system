"""Unit tests: app.api.routes.auth"""
import pytest


@pytest.mark.asyncio
async def test_login_success(client, db_session):
    """
    Успешный логин по username и password.
    Вход: Пользователь в БД; POST /api/auth/login с верными полями (пароль не короче 8 символов).
    Выход: HTTP 200; JSON с access_token.
    """
    from app.models.user import User
    from app.core.security import get_password_hash

    db_session.add(User(username="loginu", hashed_password=get_password_hash("secretpass"), is_active=True))
    await db_session.commit()

    r = await client.post("/api/auth/login", json={"username": "loginu", "password": "secretpass"})
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client, db_session):
    """
    Неверный пароль при существующем пользователе.
    Вход: Пользователь в БД; POST с неверным password.
    Выход: HTTP 401.
    """
    from app.models.user import User
    from app.core.security import get_password_hash

    db_session.add(User(username="u2", hashed_password=get_password_hash("password1"), is_active=True))
    await db_session.commit()

    r = await client.post("/api/auth/login", json={"username": "u2", "password": "wrongpass"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    """
    Логин несуществующего пользователя.
    Вход: POST с username, которого нет в БД.
    Выход: HTTP 401.
    """
    r = await client.post("/api/auth/login", json={"username": "nobody", "password": "password1"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client, db_session):
    """
    Неактивный пользователь (is_active=False) не получает токен.
    Вход: Пользователь в БД с is_active=False; верный пароль по схеме UserCreate.
    Выход: HTTP 403.
    """
    from app.models.user import User
    from app.core.security import get_password_hash

    db_session.add(User(username="inact", hashed_password=get_password_hash("password1"), is_active=False))
    await db_session.commit()

    r = await client.post("/api/auth/login", json={"username": "inact", "password": "password1"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_me_authenticated(client, auth_headers):
    """
    GET /api/auth/me с валидным JWT.
    Вход: Заголовок Authorization из фикстуры auth_headers.
    Выход: HTTP 200 (username совпадает с пользователем testuser).
    """
    r = await client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "testuser"


@pytest.mark.asyncio
async def test_me_no_token(client):
    """
    GET /api/auth/me без токена.
    Вход: Запрос без Authorization.
    Выход: HTTP 401.
    """
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_success(client, auth_headers):
    """
    Смена пароля при верном текущем пароле.
    Вход: Заголовок Authorization из фикстуры auth_headers; тело {"current_password": "testpass123", "new_password": "newpass12345"}.
    Выход: HTTP 200.
    """
    r = await client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "testpass123", "new_password": "newpass12345"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(client, auth_headers):
    """
    Смена пароля при неверном current_password.
    Вход: Заголовок Authorization из фикстуры auth_headers; тело {"current_password": "wrong", "new_password": "newpass12345"}.
    Выход: HTTP 400.
    """
    r = await client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "newpass12345"},
    )
    assert r.status_code == 400
