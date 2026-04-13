"""Unit tests: app.api.deps"""
import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from app.api.deps import get_client_ip, require_user
from app.models.user import User


def test_get_client_ip_from_forwarded():
    """
    IP клиента из X-Forwarded-For (первый адрес в цепочке).
    Вход: request с заголовком X-Forwarded-For и другим client.host.
    Выход: строка "1.2.3.4".
    """
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
    req.client = MagicMock(host="10.0.0.2")
    assert get_client_ip(req) == "1.2.3.4"


def test_get_client_ip_from_client_host():
    """
    IP из request.client.host, если X-Forwarded-For нет.
    Вход: пустой headers; client.host="10.0.0.1".
    Выход: строка "10.0.0.1".
    """
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock(host="10.0.0.1")
    assert get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_no_client():
    """
    Нет client - IP не определён.
    Вход: req.client is None.
    Выход: None.
    """
    req = MagicMock()
    req.headers = {}
    req.client = None
    assert get_client_ip(req) is None


@pytest.mark.asyncio
async def test_require_user_valid():
    """
    require_user с непустым User.
    Вход: экземпляр User (is_active=True).
    Выход: тот же объект возвращается.
    """
    u = User(id=1, username="a", hashed_password="x", is_active=True)
    assert await require_user(u) is u


@pytest.mark.asyncio
async def test_require_user_none_raises_401():
    """
    require_user(None) - HTTP 401.
    Вход: None.
    Выход: HTTPException с status_code 401.
    """
    with pytest.raises(HTTPException) as ei:
        await require_user(None)
    assert ei.value.status_code == 401
