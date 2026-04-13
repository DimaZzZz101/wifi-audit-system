"""Unit tests: app.api.routes.recon"""
import pytest

from app.services import recon_service


@pytest.fixture
def patch_recon_sync(monkeypatch):
    """
    Отключает фоновый _sync_loop в recon_service (избегает долгих циклов в тестах).
    Вход: monkeypatch.
    Выход: _sync_loop заменён на no-op async.
    """
    async def _noop(*args, **kwargs):
        return

    monkeypatch.setattr(recon_service, "_sync_loop", _noop)


@pytest.mark.asyncio
async def test_start_recon(client, auth_headers, mock_tool_manager, patch_recon_sync, db_session):
    """
    POST .../recon/start - создаёт контейнер recon.
    Вход: Проект active; JSON {"interface": "wlan0"}.
    Выход: HTTP 200; в вызове create_container image и cap_add ожидаемые.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "ReconProj"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})

    r = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={"interface": "wlan0"},
    )
    assert r.status_code == 200
    mock_tool_manager["tool_manager_create_container"].assert_awaited()
    call = mock_tool_manager["tool_manager_create_container"].await_args
    body = call.args[1] if len(call.args) > 1 else call.kwargs.get("body")
    assert body["image"] == "wizzard_tools-recon:latest"
    assert set(body["cap_add"]) >= {"NET_ADMIN", "NET_RAW", "SYS_MODULE"}


@pytest.mark.asyncio
async def test_start_recon_no_interface(client, auth_headers, db_session):
    """
    Старт recon без обязательного interface.
    Вход: Тело {}.
    Выход: HTTP 422.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "R2"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})

    r = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_stop_recon(client, auth_headers, mock_tool_manager, patch_recon_sync, db_session):
    """
    POST .../recon/{scan_id}/stop.
    Вход: scan_id из ответа start.
    Выход: HTTP 200; stop_container вызван.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "R3"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})

    sr = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={"interface": "wlan0"},
    )
    scan_id = sr.json()["scan_id"]

    r = await client.post(
        f"/api/projects/{pid}/recon/{scan_id}/stop",
        headers=auth_headers,
    )
    assert r.status_code == 200
    mock_tool_manager["tool_manager_stop_container"].assert_awaited()


@pytest.mark.asyncio
async def test_recon_status(client, auth_headers, mock_tool_manager, patch_recon_sync, db_session):
    """
    GET .../recon/{scan_id}/status.
    Вход: scan_id после start.
    Выход: HTTP 200; ключи is_running, ap_count, sta_count.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "R4"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})
    sr = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={"interface": "wlan0"},
    )
    scan_id = sr.json()["scan_id"]

    r = await client.get(
        f"/api/projects/{pid}/recon/{scan_id}/status",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "is_running" in body
    assert "ap_count" in body
    assert "sta_count" in body


@pytest.mark.asyncio
async def test_list_aps(client, auth_headers, mock_tool_manager, patch_recon_sync, db_session):
    """
    GET .../recon/{scan_id}/aps.
    Вход: scan_id после start.
    Выход: HTTP 200; JSON с ключом items.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "R5"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})
    sr = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={"interface": "wlan0"},
    )
    scan_id = sr.json()["scan_id"]

    r = await client.get(
        f"/api/projects/{pid}/recon/{scan_id}/aps",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "items" in r.json()


@pytest.mark.asyncio
async def test_list_stations(client, auth_headers, mock_tool_manager, patch_recon_sync, db_session):
    """
    GET .../recon/{scan_id}/stas.
    Вход: scan_id после start.
    Выход: HTTP 200; JSON с ключом items.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "R6"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})
    sr = await client.post(
        f"/api/projects/{pid}/recon/start",
        headers=auth_headers,
        json={"interface": "wlan0"},
    )
    scan_id = sr.json()["scan_id"]

    r = await client.get(
        f"/api/projects/{pid}/recon/{scan_id}/stas",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "items" in r.json()
