"""Unit tests: app.api.routes.hardware"""
import json
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_hardware_summary(client, auth_headers, mock_tool_manager):
    """
    GET /api/hardware/summary - агрегат с TOOL-manager.
    Вход: JWT; мок tool_manager_hardware_summary возвращает usb_devices и network_interfaces.
    Выход: HTTP 200; непустые usb_devices и network_interfaces.
    """
    mock_tool_manager["tool_manager_hardware_summary"].return_value = {
        "usb_devices": [{"bus": "1", "device": "2", "id": "0:0", "name": "Dev", "wifi_capable": False}],
        "pci_devices": [],
        "network_interfaces": [{"name": "wlan0", "flags": "", "wireless": True}],
        "filesystem": [],
    }

    r = await client.get("/api/hardware/summary", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["usb_devices"]) >= 1
    assert len(body["network_interfaces"]) >= 1


@pytest.mark.asyncio
async def test_hardware_summary_tool_manager_down(client, auth_headers, monkeypatch):
    """
    Эндпоинт summary при None от tool_manager_hardware_summary.
    Вход: AsyncMock возвращает None.
    Выход: HTTP 200 (обработка без 5xx).
    """
    monkeypatch.setattr(
        "app.services.tool_manager_client.tool_manager_hardware_summary",
        AsyncMock(return_value=None),
    )

    r = await client.get("/api/hardware/summary", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_wifi_configure(client, auth_headers, mock_tool_manager):
    """
    POST /api/hardware/wifi-adapter/{name}/configure.
    Вход: name=wlan0, body {"mode": "monitor"}; мок tool_manager_run_tool успешный.
    Выход: HTTP 200.
    """
    mock_tool_manager["tool_manager_run_tool"].return_value = {
        "stdout": json.dumps({"ok": True, "mode": "monitor"}),
        "stderr": "",
        "exit_code": 0,
    }

    r = await client.post(
        "/api/hardware/wifi-adapter/wlan0/configure",
        headers=auth_headers,
        json={"mode": "monitor"},
    )
    assert r.status_code == 200
