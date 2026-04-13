"""Unit tests: app.api.routes.metrics"""
import pytest


@pytest.mark.asyncio
async def test_get_metrics_authenticated(client, auth_headers, monkeypatch):
    """
    GET /api/metrics/system с авторизацией.
    Вход: JWT; monkeypatch get_system_metrics на фиктивный payload (host, cpu, memory, containers, disk).
    Выход: HTTP 200; в теле есть ключи host и containers.
    """
    async def fake_metrics(**kwargs):
        return {
            "host": {"cpu_percent": 1.0},
            "cpu": {"percent": 1.0, "containers_count": 0},
            "memory": {"used_mb": 1.0, "limit_mb": 100.0, "percent": 1.0},
            "containers": [],
            "disk": {"used_gb": 0.0, "total_gb": 1.0, "percent": 0.0, "path": "/"},
        }

    monkeypatch.setattr("app.services.metrics_service.get_system_metrics", fake_metrics)

    r = await client.get("/api/metrics/system", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "host" in body
    assert "containers" in body


@pytest.mark.asyncio
async def test_get_metrics_no_auth(client):
    """
    GET /api/metrics/system без JWT.
    Вход: Запрос без Authorization.
    Выход: HTTP 401.
    """
    r = await client.get("/api/metrics/system")
    assert r.status_code == 401
