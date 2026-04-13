"""Unit tests: app.api.routes.projects"""
import pytest


@pytest.mark.asyncio
async def test_create_project(client, auth_headers):
    """
    POST /api/projects - создание проекта.
    Вход: JSON {"name": "Test Project"}; JWT.
    Выход: HTTP 201; в теле id, slug; name совпадает.
    """
    r = await client.post(
        "/api/projects",
        headers=auth_headers,
        json={"name": "Test Project"},
    )
    assert r.status_code == 201
    body = r.json()
    assert "id" in body and "slug" in body and body["name"] == "Test Project"


@pytest.mark.asyncio
async def test_create_project_duplicate_name(client, auth_headers):
    """
    Повторное создание с тем же уникальным именем.
    Вход: Два POST с одинаковым name.
    Выход: HTTP 409.
    """
    await client.post("/api/projects", headers=auth_headers, json={"name": "Dup Name"})
    r2 = await client.post("/api/projects", headers=auth_headers, json={"name": "Dup Name"})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_projects(client, auth_headers):
    """
    GET /api/projects - список проектов.
    Вход: Два POST с разными name.
    Выход: HTTP 200; len(json) >= 2.
    """
    await client.post("/api/projects", headers=auth_headers, json={"name": "P1"})
    await client.post("/api/projects", headers=auth_headers, json={"name": "P2"})
    r = await client.get("/api/projects", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 2


@pytest.mark.asyncio
async def test_get_project(client, auth_headers):
    """
    GET /api/projects/{id}.
    Вход: id из ответа POST создания.
    Выход: HTTP 200; id в теле совпадает.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "Single"})
    pid = cr.json()["id"]
    r = await client.get(f"/api/projects/{pid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == pid


@pytest.mark.asyncio
async def test_get_project_not_found(client, auth_headers):
    """
    GET несуществующего проекта.
    Вход: id=99999 (нет в БД).
    Выход: HTTP 404.
    """
    r = await client.get("/api/projects/99999", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_project(client, auth_headers):
    """
    DELETE /api/projects/{id}.
    Вход: id из ответа POST создания.
    Выход: HTTP 204.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "ToDel"})
    pid = cr.json()["id"]
    r = await client.delete(f"/api/projects/{pid}", headers=auth_headers)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_update_project_mac_filter(client, auth_headers):
    """
    PUT /api/projects/{id}/mac-filter.
    Вход: id из ответа POST создания; filter_type whitelist, entries с MAC.
    Выход: HTTP 200; filter_type и entries в ответе совпадают.
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "MacProj"})
    pid = cr.json()["id"]
    r = await client.put(
        f"/api/projects/{pid}/mac-filter",
        headers=auth_headers,
        json={"filter_type": "whitelist", "entries": ["AA:BB:CC:DD:EE:FF"]},
    )
    assert r.status_code == 200
    assert r.json()["filter_type"] == "whitelist"
    assert "AA:BB:CC:DD:EE:FF" in r.json()["entries"]


@pytest.mark.asyncio
async def test_project_requires_auth(client):
    """
    Защищённый маршрут без JWT.
    Вход: GET /api/projects без Authorization.
    Выход: HTTP 401.
    """
    r = await client.get("/api/projects")
    assert r.status_code == 401
