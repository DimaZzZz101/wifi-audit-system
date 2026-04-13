"""Attack service: start/stop attack containers, sync loop for status polling."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker
from app.models.audit import AuditJob, AuditPlan
from app.services.audit_storage import build_audit_storage_dirname
from app.services import tool_manager_client
from app.services.session_service import get_project_dir

ATTACK_IMAGE = "wizzard_tools-attack:latest"
SYNC_INTERVAL = 3.0
ATTACK_STOP_TIMEOUT = 30
GRACEFUL_STOP_WAIT = 30

_active_sync_tasks: dict[str, asyncio.Task] = {}
_active_stop_tasks: dict[str, asyncio.Task] = {}
_host_artifacts_path: str | None = None


def _resolve_host_artifacts_path() -> str:
    global _host_artifacts_path
    if _host_artifacts_path is not None:
        return _host_artifacts_path
    settings = get_settings()
    if settings.artifacts_host_path:
        _host_artifacts_path = settings.artifacts_host_path
        return _host_artifacts_path
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 5 and parts[4] == settings.artifacts_dir:
                    _host_artifacts_path = parts[3]
                    return _host_artifacts_path
    except OSError:
        pass
    _host_artifacts_path = settings.artifacts_dir
    return _host_artifacts_path


async def start_job(
    token: str,
    job_id: str,
    project_slug: str,
) -> dict[str, Any]:
    """Launch an attack container for the given job."""
    async with async_session_maker() as db:
        row = await db.execute(select(AuditJob).where(AuditJob.id == uuid.UUID(job_id)))
        job = row.scalar_one_or_none()
        if not job:
            return {"error": "Job not found"}

        plan_row = await db.execute(select(AuditPlan).where(AuditPlan.id == job.audit_plan_id))
        plan = plan_row.scalar_one_or_none()

        attack_type = job.attack_type
        config = dict(job.config or {})
        config.setdefault("bssid", plan.bssid if plan else "")
        config.setdefault("essid", plan.essid if plan else "")
        config.setdefault("interface", job.interface or "")
        if attack_type == "pmkid_capture" and plan:
            # PMKID must always target the AP fixed at audit plan creation time.
            config["bssid"] = plan.bssid
            config["channel"] = plan.ap_snapshot.get("channel") if isinstance(plan.ap_snapshot, dict) else config.get("channel")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        job_folder = f"{job.order_index:02d}-{attack_type}"
        audit_folder = str(job.audit_plan_id)
        if plan:
            audit_folder = build_audit_storage_dirname(
                plan_id=plan.id,
                created_at=plan.created_at,
                essid=plan.essid,
                bssid=plan.bssid,
            )

        audit_dir = get_project_dir(project_slug) / "audits" / audit_folder / "jobs" / job_folder
        audit_dir.mkdir(parents=True, exist_ok=True)

        stop_flag = audit_dir / ".stop_requested"
        if stop_flag.exists():
            stop_flag.unlink()

        host_base = _resolve_host_artifacts_path()
        host_audit_dir = str(Path(host_base) / "projects" / project_slug / "audits" / audit_folder / "jobs" / job_folder)

        settings = get_settings()
        dict_host_path = str(Path(host_base) / "dictionaries")

        container_name = f"wifiaudit-attack-{attack_type}-{ts}"
        env = {
            "ATTACK_TYPE": attack_type,
            "ATTACK_CONFIG": json.dumps(config),
            "ATTACK_DATA_DIR": "/data/attack",
        }

        volumes = [f"{host_audit_dir}:/data/attack"]
        dict_dir = Path(settings.artifacts_dir) / "dictionaries"
        if dict_dir.exists():
            volumes.append(f"{dict_host_path}:/data/dictionaries:ro")

        if attack_type == "psk_crack":
            source_dir = config.get("_source_job_dir")
            if source_dir:
                host_source = str(Path(host_base) / Path(source_dir).relative_to(Path(settings.artifacts_dir)))
                volumes.append(f"{host_source}:/data/capture:ro")

        try:
            result = await tool_manager_client.tool_manager_create_container(
                token=token,
                body={
                    "image": ATTACK_IMAGE,
                    "name": container_name,
                    "container_type": "attack",
                    "env": env,
                    "network_mode": "host",
                    "cap_add": ["NET_ADMIN", "NET_RAW", "SYS_MODULE"],
                    "volumes": volumes,
                },
            )
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text[:300]
            raise RuntimeError(f"Tool-manager error ({e.response.status_code}): {detail}") from e

        container_id = result.get("id")

        job.status = "running"
        job.container_id = container_id
        job.started_at = datetime.now(timezone.utc)
        job.stopped_at = None
        job.result = None
        job.artifact_paths = None
        job.log_path = str(audit_dir / "log.txt")
        await db.commit()

    task = asyncio.create_task(
        _sync_loop(job_id, audit_dir, token=token, container_id=container_id,
                   project_slug=project_slug)
    )
    _active_sync_tasks[job_id] = task

    return {"job_id": job_id, "container_id": container_id, "status": "running"}


async def stop_job(token: str, job_id: str) -> dict[str, Any]:
    """Request graceful stop: write flag file, mark as 'stopping', let sync_loop handle cleanup."""
    container_id: str | None = None
    async with async_session_maker() as db:
        row = await db.execute(select(AuditJob).where(AuditJob.id == uuid.UUID(job_id)))
        job = row.scalar_one_or_none()
        if not job:
            return {"error": "Job not found"}
        container_id = job.container_id

        if job.log_path:
            job_dir = Path(job.log_path).parent
            stop_flag = job_dir / ".stop_requested"
            stop_flag.write_text("1")

        job.status = "stopping"
        await db.commit()

    # Failsafe: if handler ignores stop flag, force-stop container after grace period.
    if container_id:
        prev = _active_stop_tasks.get(job_id)
        if prev and not prev.done():
            prev.cancel()
        _active_stop_tasks[job_id] = asyncio.create_task(
            _force_stop_if_stuck(token=token, job_id=job_id, container_id=container_id)
        )

    return {"job_id": job_id, "status": "stopping"}


async def restart_job(job_id: str) -> dict[str, Any]:
    """Reset a completed/failed/stopped job back to pending for re-run."""
    async with async_session_maker() as db:
        row = await db.execute(select(AuditJob).where(AuditJob.id == uuid.UUID(job_id)))
        job = row.scalar_one_or_none()
        if not job:
            raise ValueError("Job not found")
        if job.status == "running":
            raise ValueError("Cannot restart a running job")

        run_count = (job.config or {}).get("_run_count", 0) + 1
        new_config = dict(job.config or {})
        new_config["_run_count"] = run_count

        job.status = "pending"
        job.config = new_config
        job.container_id = None
        job.started_at = None
        job.stopped_at = None
        job.result = None
        job.artifact_paths = None
        await db.commit()
        return _job_to_dict(job)


async def _remove_container(token: str | None, container_id: str | None) -> None:
    if not token or not container_id:
        return
    try:
        await tool_manager_client.tool_manager_stop_container(
            token=token, container_id=container_id, remove=True, stop_timeout=ATTACK_STOP_TIMEOUT,
        )
    except Exception:
        pass


async def _force_stop_if_stuck(token: str, job_id: str, container_id: str) -> None:
    """Force stop a stuck job after grace timeout if still running/stopping."""
    try:
        await asyncio.sleep(GRACEFUL_STOP_WAIT)
        async with async_session_maker() as db:
            row = await db.execute(select(AuditJob).where(AuditJob.id == uuid.UUID(job_id)))
            job = row.scalar_one_or_none()
            if not job:
                return
            if job.status not in ("running", "stopping"):
                return
            if job.container_id != container_id:
                return

        await _remove_container(token, container_id)

        async with async_session_maker() as db:
            await db.execute(
                update(AuditJob)
                .where(AuditJob.id == uuid.UUID(job_id))
                .values(
                    status="stopped",
                    stopped_at=datetime.now(timezone.utc),
                    container_id=None,
                )
            )
            await db.commit()
    except asyncio.CancelledError:
        pass
    finally:
        _active_stop_tasks.pop(job_id, None)


async def _sync_loop(
    job_id: str,
    job_dir: Path,
    *,
    token: str | None = None,
    container_id: str | None = None,
    project_slug: str = "",
) -> None:
    """Poll status.json written by the attack container, update DB.
    Also handles graceful stop: waits for container to finish post-processing."""
    job_uuid = uuid.UUID(job_id)
    try:
        while True:
            await asyncio.sleep(SYNC_INTERVAL)
            status_path = job_dir / "status.json"
            if not status_path.exists():
                continue

            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            container_status = status.get("status", "running")

            if container_status in ("completed", "failed", "stopped"):
                result_data = None
                result_path = job_dir / "result.json"
                if result_path.exists():
                    try:
                        result_data = json.loads(result_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        pass

                artifacts = _collect_artifacts(job_dir)

                async with async_session_maker() as db:
                    await db.execute(
                        update(AuditJob)
                        .where(AuditJob.id == job_uuid)
                        .values(
                            status=container_status,
                            stopped_at=datetime.now(timezone.utc),
                            container_id=None,
                            result=result_data,
                            artifact_paths=artifacts,
                        )
                    )
                    await db.commit()

                await _remove_container(token, container_id)
                stop_task = _active_stop_tasks.pop(job_id, None)
                if stop_task and not stop_task.done():
                    stop_task.cancel()

                await _check_dependency_unlock(job_uuid, result_data)

                break

    except asyncio.CancelledError:
        pass
    finally:
        _active_sync_tasks.pop(job_id, None)


async def _check_dependency_unlock(job_uuid: uuid.UUID, result_data: dict | None) -> None:
    """After handshake/pmkid capture completes, auto-configure psk_crack if handshake was found."""
    if not result_data:
        return

    handshake_found = result_data.get("handshake_found", False)
    pmkid_found = result_data.get("pmkid_found", False)

    if not handshake_found and not pmkid_found:
        return

    async with async_session_maker() as db:
        row = await db.execute(select(AuditJob).where(AuditJob.id == job_uuid))
        completed_job = row.scalar_one_or_none()
        if not completed_job:
            return

        crack_rows = await db.execute(
            select(AuditJob).where(
                AuditJob.audit_plan_id == completed_job.audit_plan_id,
                AuditJob.attack_type == "psk_crack",
            )
        )
        crack_job = crack_rows.scalar_one_or_none()
        if not crack_job or crack_job.status != "pending":
            return

        new_config = dict(crack_job.config or {})

        source_job_dir = None
        if completed_job.log_path:
            source_job_dir = str(Path(completed_job.log_path).parent)

        if handshake_found:
            hc = result_data.get("hc22000")
            pcap = result_data.get("handshake_pcap")
            if hc:
                new_config["hc22000"] = hc
            if pcap:
                new_config["pcap"] = pcap
        elif pmkid_found:
            hc = result_data.get("hc22000")
            if hc:
                new_config["hc22000"] = hc

        new_config["_capture_ready"] = True
        new_config["_source_job"] = str(completed_job.id)
        if source_job_dir:
            new_config["_source_job_dir"] = source_job_dir
        crack_job.config = new_config
        await db.commit()


def _collect_artifacts(job_dir: Path) -> dict[str, str]:
    """Scan job directory for known artifact files."""
    artifacts: dict[str, str] = {}
    patterns = {
        "pcap": ["*.pcap", "*.cap"],
        "pcapng": ["*.pcapng"],
        "hc22000": ["*.hc22000"],
        "handshake": ["handshake.*"],
        "cracked": ["cracked.txt", "found.txt"],
    }
    for key, globs in patterns.items():
        for g in globs:
            for f in job_dir.glob(g):
                artifacts[key] = str(f)
                break
    return artifacts


def _job_to_dict(job: AuditJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "audit_plan_id": str(job.audit_plan_id),
        "attack_type": job.attack_type,
        "order_index": job.order_index,
        "status": job.status,
        "config": job.config,
        "container_id": job.container_id,
        "interface": job.interface,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "stopped_at": job.stopped_at.isoformat() if job.stopped_at else None,
        "result": job.result,
        "log_path": job.log_path,
        "artifact_paths": job.artifact_paths,
    }


async def shutdown_all_attack_tasks() -> None:
    for _, task in _active_sync_tasks.items():
        if not task.done():
            task.cancel()
    for task in _active_sync_tasks.values():
        try:
            await task
        except asyncio.CancelledError:
            pass
    for _, task in _active_stop_tasks.items():
        if not task.done():
            task.cancel()
    for task in _active_stop_tasks.values():
        try:
            await task
        except asyncio.CancelledError:
            pass
    _active_sync_tasks.clear()
    _active_stop_tasks.clear()
