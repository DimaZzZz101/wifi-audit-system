"""Unit tests: app.routes_tools (POST /tools/run)."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_tool_run_success(client):
    """
    POST /tools/run - контейнер завершился с кодом 0.
    Вход: JSON image и timeout; patch run_tool -> exit_code 0, stdout "ok".
    Выход: HTTP 200; в JSON exit_code == 0.
    """
    with patch(
        "app.routes_tools.container_service.run_tool",
        AsyncMock(return_value={"stdout": "ok", "stderr": "", "exit_code": 0}),
    ):
        r = await client.post(
            "/tools/run",
            headers={"Authorization": "Bearer x"},
            json={"image": "wizzard_tools-wifi-info:latest", "timeout": 30},
        )
    assert r.status_code == 200
    body = r.json()
    assert body.get("exit_code") == 0


@pytest.mark.asyncio
async def test_tool_run_failure(client):
    """
    POST /tools/run - ненулевой exit_code от контейнера.
    Вход: JSON image и timeout; patch run_tool -> exit_code 1, stderr "fail".
    Выход: HTTP 200 у API; в теле exit_code == 1 (ошибка инструмента, не HTTP).
    """
    with patch(
        "app.routes_tools.container_service.run_tool",
        AsyncMock(return_value={"stdout": "", "stderr": "fail", "exit_code": 1}),
    ):
        r = await client.post(
            "/tools/run",
            headers={"Authorization": "Bearer x"},
            json={"image": "bad:latest", "timeout": 30},
        )
    assert r.status_code == 200
    assert r.json().get("exit_code") == 1
