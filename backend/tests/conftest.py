"""Фикстуры pytest: PostgreSQL, ASGI-клиент FastAPI, JWT, моки TOOL-manager.

Переменные окружения: DATABASE_URL / TEST_DATABASE_URL, SECRET_KEY, ARTIFACTS_DIR.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Must run before app.database is imported (engine uses DATABASE_URL at import time).
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://wifiaudit:wifiaudit@127.0.0.1:5432/wifiaudit_test",
    ),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long!!")
if not os.environ.get("ARTIFACTS_DIR"):
    _ad = tempfile.mkdtemp(prefix="wifiaudit-artifacts-")
    os.environ["ARTIFACTS_DIR"] = _ad
    os.environ["ARTIFACTS_HOST_PATH"] = _ad

from app.database import Base, async_session_maker, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.api.deps import get_session  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    """Цикл событий asyncio на всю сессию тестов."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def prepare_db():
    """Создаёт схему БД в начале сессии, drop_all в конце; skip, если Postgres недоступен."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except OSError as e:
        pytest.skip(f"PostgreSQL недоступен (проверьте TEST_DATABASE_URL): {e}")
    except Exception as e:
        if "Connect" in type(e).__name__ or "connection" in str(e).lower():
            pytest.skip(f"PostgreSQL недоступен: {e}")
        raise
    yield
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


@pytest_asyncio.fixture
async def db_session(prepare_db) -> AsyncIterator[AsyncSession]:
    """Сессия SQLAlchemy; после теста - TRUNCATE перечисленных таблиц."""
    async with async_session_maker() as session:
        yield session
        await session.rollback()

    async with async_session_maker() as s:
        await s.execute(
            text(
                """
                TRUNCATE TABLE
                    audit_log,
                    recon_sta,
                    recon_ap,
                    recon_scan,
                    audit_job,
                    audit_plan,
                    dictionary,
                    registry_image,
                    project,
                    system_settings,
                    users
                RESTART IDENTITY CASCADE;
                """
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """HTTPX AsyncClient к приложению; get_session подменён на db_session."""
    async def _get_session_override():
        yield db_session

    app.dependency_overrides[get_session] = _get_session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_user(db_session: AsyncSession) -> User:
    """Пользователь testuser в БД с известным паролем."""
    u = User(
        username="testuser",
        hashed_password=get_password_hash("testpass123"),
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def auth_headers(auth_user: User) -> dict[str, str]:
    """Заголовок Authorization: Bearer для auth_user."""
    token = create_access_token(auth_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_tool_manager(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Подмена асинхронных вызовов к TOOL-manager; возвращает словарь AsyncMock по именам."""
    from app.services import tool_manager_client as tm

    mocks: dict[str, AsyncMock] = {
        "tool_manager_list_containers": AsyncMock(return_value=[]),
        "tool_manager_get_container": AsyncMock(return_value=None),
        "tool_manager_create_container": AsyncMock(
            return_value={"id": "mock-container-id", "name": "mock", "image": "x", "status": "running"}
        ),
        "tool_manager_stop_container": AsyncMock(return_value={"id": "x", "stopped": True}),
        "tool_manager_run_tool": AsyncMock(
            return_value={"stdout": '{"mode":"monitor"}', "stderr": "", "exit_code": 0}
        ),
        "tool_manager_list_images": AsyncMock(return_value=[]),
        "tool_manager_pull_image": AsyncMock(return_value={"pulled": True, "image": "t"}),
        "tool_manager_hardware_summary": AsyncMock(
            return_value={
                "usb_devices": [],
                "pci_devices": [],
                "network_interfaces": [],
                "filesystem": [],
            }
        ),
    }
    for name, m in mocks.items():
        monkeypatch.setattr(tm, name, m)
    return mocks
