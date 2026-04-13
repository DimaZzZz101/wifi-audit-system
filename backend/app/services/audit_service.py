"""Audit service: create audit plans (B&B), manage job pipelines."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models.audit import AuditJob, AuditPlan
from app.models.recon import ReconAP, ReconScan
from app.models.system_settings import SystemSettings
from app.services import bb_solver
from app.services.session_service import get_project_dir


ATTACK_TYPE_BY_INDEX = {
    1: "handshake_capture",
    2: "pmkid_capture",
    3: "wps_pixie",
    4: "dragonshift",
    5: "psk_crack",
    7: "dos",
}


async def get_audit_settings() -> dict[str, Any]:
    """Load audit settings from system_settings or return defaults."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(SystemSettings).where(SystemSettings.key == "audit_params")
        )
        setting = row.scalar_one_or_none()
        if setting:
            return setting.value
    return _default_settings()


_HIDDEN_ATTACKS = {"recon", "krack"}


def _default_settings() -> dict[str, Any]:
    return {
        "attacks": [
            {"name": n, "weight": w, "time_s": t}
            for n, w, t in bb_solver.DEFAULT_ATTACKS
            if n not in _HIDDEN_ATTACKS
        ],
        "time_budget_s": 28800.0,
    }


async def create_audit_plan(
    project_id: int,
    bssid: str,
    scan_id: str,
) -> dict[str, Any]:
    """Run B&B solver for the given AP and create a plan with jobs."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(ReconAP).where(
                ReconAP.scan_id == uuid.UUID(scan_id),
                ReconAP.bssid == bssid.upper(),
            )
        )
        ap = row.scalar_one_or_none()
        if not ap:
            raise ValueError(f"AP {bssid} not found in scan {scan_id}")

        ap_data = _ap_to_dict(ap)
        ap_data["scan_id"] = scan_id

    settings = await get_audit_settings()
    user_attacks = {a["name"]: a for a in settings.get("attacks", [])}
    time_budget = settings.get("time_budget_s", 28800.0)

    attack_tuples = []
    for name, default_w, default_t in bb_solver.DEFAULT_ATTACKS:
        if name in user_attacks:
            a = user_attacks[name]
            attack_tuples.append((name, a["weight"], a["time_s"]))
        else:
            attack_tuples.append((name, default_w, default_t))

    ap_params = bb_solver.ap_params_from_recon(ap_data)
    result = bb_solver.solve(ap_params, attack_tuples, time_budget)

    plan_id = uuid.uuid4()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bssid_safe = bssid.replace(":", "_")

    async with async_session_maker() as db:
        plan = AuditPlan(
            id=plan_id,
            project_id=project_id,
            bssid=bssid.upper(),
            essid=ap_data.get("essid"),
            ap_snapshot=ap_data,
            status="pending",
            time_budget_s=int(time_budget),
            bb_solution={
                "scan_id": scan_id,
                "f_star": result.f_star,
                "selected_attacks": result.selected_attacks,
                "execution_order": result.execution_order,
                "total_time_s": result.total_time_s,
                "nodes_visited": result.nodes_visited,
            },
        )
        db.add(plan)
        await db.flush()

        for idx, atk in enumerate(result.selected_attacks):
            attack_name = atk["name"]
            job_config: dict[str, Any] = {
                "bssid": bssid.upper(),
                "channel": ap_data.get("channel"),
                "timeout": int(atk["time_s"]),
            }
            if attack_name == "dragonshift":
                job_config["essid"] = ap_data.get("essid") or ""
            job = AuditJob(
                audit_plan_id=plan_id,
                attack_type=attack_name,
                order_index=idx,
                status="pending",
                config=job_config,
            )
            db.add(job)

        await db.commit()

    return await get_audit_plan(str(plan_id))


async def get_audit_plan(plan_id: str) -> dict[str, Any]:
    """Get an audit plan with its jobs."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditPlan).where(AuditPlan.id == uuid.UUID(plan_id))
        )
        plan = row.scalar_one_or_none()
        if not plan:
            raise ValueError("Plan not found")

        jobs_rows = await db.execute(
            select(AuditJob)
            .where(AuditJob.audit_plan_id == plan.id)
            .order_by(AuditJob.order_index)
        )
        jobs = jobs_rows.scalars().all()
        scan_id = _extract_scan_id(plan)
        if not scan_id:
            scan_row = await db.execute(
                select(ReconAP.scan_id)
                .join(ReconScan, ReconScan.id == ReconAP.scan_id)
                .where(
                    ReconAP.bssid == plan.bssid,
                    ReconScan.project_id == plan.project_id,
                )
                .order_by(ReconScan.started_at.desc())
                .limit(1)
            )
            latest_scan_id = scan_row.scalar_one_or_none()
            if latest_scan_id is not None:
                scan_id = str(latest_scan_id)

        return {
            "id": str(plan.id),
            "project_id": plan.project_id,
            "scan_id": scan_id,
            "bssid": plan.bssid,
            "essid": plan.essid,
            "status": plan.status,
            "time_budget_s": plan.time_budget_s,
            "bb_solution": plan.bb_solution,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
            "jobs": [_job_to_dict(j) for j in jobs],
        }


async def list_audit_plans(project_id: int) -> list[dict[str, Any]]:
    """List all audit plans for a project."""
    async with async_session_maker() as db:
        rows = await db.execute(
            select(AuditPlan)
            .where(AuditPlan.project_id == project_id)
            .order_by(AuditPlan.created_at.desc())
        )
        plans = rows.scalars().all()

        result = []
        for p in plans:
            jobs_count_row = await db.execute(
                select(AuditJob)
                .where(AuditJob.audit_plan_id == p.id)
            )
            jobs_count = len(jobs_count_row.scalars().all())
            result.append({
                "id": str(p.id),
                "bssid": p.bssid,
                "essid": p.essid,
                "status": p.status,
                "time_budget_s": p.time_budget_s,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "job_count": jobs_count,
            })
        return result


async def delete_audit_plan(plan_id: str) -> None:
    """Delete (cancel) an audit plan and its jobs."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditPlan).where(AuditPlan.id == uuid.UUID(plan_id))
        )
        plan = row.scalar_one_or_none()
        if plan:
            await db.delete(plan)
            await db.commit()


async def start_plan(plan_id: str) -> dict[str, Any]:
    """Mark a plan as running."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditPlan).where(AuditPlan.id == uuid.UUID(plan_id))
        )
        plan = row.scalar_one_or_none()
        if not plan:
            raise ValueError("Plan not found")
        plan.status = "running"
        await db.commit()
        return {"plan_id": str(plan.id), "status": "running"}


async def get_job(job_id: str) -> dict[str, Any] | None:
    """Get a single audit job."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditJob).where(AuditJob.id == uuid.UUID(job_id))
        )
        job = row.scalar_one_or_none()
        return _job_to_dict(job) if job else None


async def update_job(job_id: str, config: dict | None = None, interface: str | None = None) -> dict[str, Any]:
    """Update job config before running."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditJob).where(AuditJob.id == uuid.UUID(job_id))
        )
        job = row.scalar_one_or_none()
        if not job:
            raise ValueError("Job not found")
        if config is not None:
            job.config = {**job.config, **config}
        if interface is not None:
            job.interface = interface
        await db.commit()
        return _job_to_dict(job)


async def skip_job(job_id: str) -> dict[str, Any]:
    """Mark a job as skipped."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(AuditJob).where(AuditJob.id == uuid.UUID(job_id))
        )
        job = row.scalar_one_or_none()
        if not job:
            raise ValueError("Job not found")
        job.status = "skipped"
        await db.commit()
        return _job_to_dict(job)


async def update_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Save audit settings to system_settings table."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(SystemSettings).where(SystemSettings.key == "audit_params")
        )
        setting = row.scalar_one_or_none()
        if setting:
            setting.value = data
        else:
            db.add(SystemSettings(key="audit_params", value=data))
        await db.commit()
    return data


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


def _ap_to_dict(ap: ReconAP) -> dict[str, Any]:
    return {
        "bssid": ap.bssid,
        "essid": ap.essid,
        "is_hidden": ap.is_hidden,
        "channel": ap.channel,
        "band": ap.band,
        "power": ap.power,
        "speed": ap.speed,
        "privacy": ap.privacy,
        "cipher": ap.cipher,
        "auth": ap.auth,
        "beacons": ap.beacons,
        "data_frames": ap.data_frames,
        "iv_count": ap.iv_count,
        "wps": ap.wps,
        "security_info": ap.security_info,
        "tagged_params": ap.tagged_params,
        "first_seen": ap.first_seen.isoformat() if ap.first_seen else None,
        "last_seen": ap.last_seen.isoformat() if ap.last_seen else None,
        "client_count": ap.client_count,
    }


def _extract_scan_id(plan: AuditPlan) -> str | None:
    bb = plan.bb_solution or {}
    scan_id = bb.get("scan_id")
    if isinstance(scan_id, str) and scan_id:
        return scan_id

    ap_snapshot = plan.ap_snapshot or {}
    scan_id = ap_snapshot.get("scan_id")
    if isinstance(scan_id, str) and scan_id:
        return scan_id

    return None
