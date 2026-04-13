"""Unit tests: app.api.routes.audit"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.recon import ReconAP, ReconScan


async def _active_project_and_scan(client, auth_headers, db_session):
    """
    Вспомогательно: проект в статусе active, ReconScan и ReconAP в БД.
    Вход: client с JWT, db_session.
    Выход: кортеж (project_id, scan_id строкой UUID).
    """
    cr = await client.post("/api/projects", headers=auth_headers, json={"name": "AuditProj"})
    pid = cr.json()["id"]
    await client.patch(f"/api/projects/{pid}", headers=auth_headers, json={"status": "active"})

    scan_id = uuid.uuid4()
    scan = ReconScan(
        id=scan_id,
        project_id=pid,
        started_at=datetime.now(timezone.utc),
        is_running=False,
        scan_mode="continuous",
        interface="wlan0",
        bands="abg",
        recon_json_path="/tmp/x",
    )
    ap = ReconAP(
        scan_id=scan_id,
        bssid="AA:BB:CC:DD:EE:FF",
        essid="test",
        channel=6,
        security_info={"display_security": "WPA2", "pmf": "none", "akm": ""},
        wps={"enabled": True},
        tagged_params={"ht_capabilities": True},
        client_count=3,
    )
    db_session.add(scan)
    await db_session.flush()
    db_session.add(ap)
    await db_session.commit()

    return pid, str(scan_id)


@pytest.mark.asyncio
async def test_create_plan(client, auth_headers, db_session):
    """
    POST /api/projects/{id}/audit/plan - построение плана аудита.
    Вход: проект active, AP в БД; тело {"bssid", "scan_id"}.
    Выход: HTTP 200; в JSON есть bb_solution.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)

    r = await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"bssid": "AA:BB:CC:DD:EE:FF", "scan_id": scan_id},
    )
    assert r.status_code == 200
    assert "bb_solution" in r.json()


@pytest.mark.asyncio
async def test_create_plan_missing_bssid(client, auth_headers, db_session):
    """
    План без bssid - ошибка валидации.
    Вход: только scan_id в теле.
    Выход: HTTP 422.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)

    r = await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"scan_id": scan_id},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_plans(client, auth_headers, db_session):
    """
    GET /api/projects/{id}/audit/plans.
    Вход: один план уже создан.
    Выход: HTTP 200; тело - list.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)
    await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"bssid": "AA:BB:CC:DD:EE:FF", "scan_id": scan_id},
    )

    r = await client.get(f"/api/projects/{pid}/audit/plans", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_start_plan(client, auth_headers, db_session):
    """
    POST /api/projects/{id}/audit/plans/{plan_id}/start.
    Вход: plan_id из ответа создания плана.
    Выход: HTTP 200; status running в JSON.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)
    pr = await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"bssid": "AA:BB:CC:DD:EE:FF", "scan_id": scan_id},
    )
    plan_id = pr.json()["id"]

    r = await client.post(
        f"/api/projects/{pid}/audit/plans/{plan_id}/start",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json().get("status") == "running"


@pytest.mark.asyncio
async def test_get_job(client, auth_headers, db_session):
    """
    GET /api/projects/{id}/audit/jobs/{job_id}.
    Вход: job_id из массива jobs ответа создания плана.
    Выход: HTTP 200; в теле есть attack_type и status.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)
    pr = await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"bssid": "AA:BB:CC:DD:EE:FF", "scan_id": scan_id},
    )
    jobs = pr.json().get("jobs") or []
    assert jobs
    job_id = jobs[0]["id"]

    r = await client.get(
        f"/api/projects/{pid}/audit/jobs/{job_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "attack_type" in body
    assert "status" in body


@pytest.mark.asyncio
async def test_stop_job(client, auth_headers, db_session, mock_tool_manager):
    """
    POST /api/projects/{id}/audit/jobs/{job_id}/stop.
    Вход: job_id первой задачи плана; моки TOOL-manager при необходимости.
    Выход: HTTP 200.
    """
    pid, scan_id = await _active_project_and_scan(client, auth_headers, db_session)
    pr = await client.post(
        f"/api/projects/{pid}/audit/plan",
        headers=auth_headers,
        json={"bssid": "AA:BB:CC:DD:EE:FF", "scan_id": scan_id},
    )
    job_id = pr.json()["jobs"][0]["id"]

    r = await client.post(
        f"/api/projects/{pid}/audit/jobs/{job_id}/stop",
        headers=auth_headers,
    )
    assert r.status_code == 200
