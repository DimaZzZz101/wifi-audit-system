"""Recon service: scan lifecycle, background sync, upsert AP/STA."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_maker
from app.models.recon import ReconAP, ReconSTA, ReconScan
from app.services import tool_manager_client
from app.services.session_service import get_project_dir

RECON_IMAGE = "wizzard_tools-recon:latest"
SYNC_INTERVAL = 3.0

_active_sync_tasks: dict[str, asyncio.Task] = {}
_host_artifacts_path: str | None = None


def _resolve_host_artifacts_path() -> str:
    """Resolve the host filesystem path that is bind-mounted as ARTIFACTS_DIR.
    Reads /proc/self/mountinfo to find the source path on the host.
    Falls back to ARTIFACTS_HOST_PATH env or ARTIFACTS_DIR."""
    global _host_artifacts_path
    if _host_artifacts_path is not None:
        return _host_artifacts_path

    settings = get_settings()
    container_mount = settings.artifacts_dir

    if settings.artifacts_host_path:
        _host_artifacts_path = settings.artifacts_host_path
        return _host_artifacts_path

    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 5 and parts[4] == container_mount:
                    _host_artifacts_path = parts[3]
                    return _host_artifacts_path
    except OSError:
        pass

    _host_artifacts_path = container_mount
    return _host_artifacts_path


async def start_scan(
    token: str,
    project_id: int,
    slug: str,
    interface: str,
    scan_mode: str = "continuous",
    scan_duration: int | None = None,
    bands: str = "abg",
    channels: str | None = None,
) -> dict[str, Any]:
    """Launch recon container and start background sync."""
    scan_uuid = uuid.uuid4()
    scan_id = str(scan_uuid)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # Human-readable artifact dir on disk (API scan_id stays UUID)
    scan_folder = f"{ts}-{scan_uuid.hex[:8]}"
    project_dir = get_project_dir(slug)
    scan_dir = project_dir / "scans" / scan_folder
    scan_dir.mkdir(parents=True, exist_ok=True)

    container_name = f"wifiaudit-{slug}-recon-{ts}"

    # Volume source must be a HOST path (docker.sock creates containers on the host).
    host_base = _resolve_host_artifacts_path()
    project_host_path = str(Path(host_base) / "projects" / slug)

    # Read MAC filter type from DB so the scanner can apply it to recon.json
    mac_filter_type: str | None = None
    async with async_session_maker() as db:
        from app.models.project import Project
        row = await db.execute(select(Project.mac_filter_type).where(Project.id == project_id))
        mac_filter_type = row.scalar_one_or_none()

    env = {
        "INTERFACE": interface,
        "SCAN_MODE": scan_mode,
        "SCAN_ID": scan_id,
        "SCAN_FOLDER": scan_folder,
        "SESSION_DIR": "/data/session",
        "BANDS": bands,
    }
    if scan_duration and scan_mode == "timed":
        env["SCAN_DURATION"] = str(scan_duration)
    if channels:
        env["CHANNELS"] = channels
    if mac_filter_type:
        env["MAC_FILTER_TYPE"] = mac_filter_type

    result = await tool_manager_client.tool_manager_create_container(
        token=token,
        body={
            "image": RECON_IMAGE,
            "name": container_name,
            "container_type": "recon",
            "env": env,
            "network_mode": "host",
            "cap_add": ["NET_ADMIN", "NET_RAW", "SYS_MODULE"],
            "volumes": [f"{project_host_path}:/data/session"],
        },
    )

    container_id = result.get("id")

    async with async_session_maker() as db:
        scan_obj = ReconScan(
            id=uuid.UUID(scan_id),
            project_id=project_id,
            started_at=datetime.now(timezone.utc),
            is_running=True,
            scan_mode=scan_mode,
            interface=interface,
            bands=bands,
            parameters={
                "scan_duration": scan_duration,
                "channels": channels,
            },
            container_id=container_id,
            recon_json_path=str(scan_dir / "recon.json"),
        )
        db.add(scan_obj)
        await db.commit()

    task = asyncio.create_task(
        _sync_loop(scan_id, scan_dir, token=token, container_id=container_id)
    )
    _active_sync_tasks[scan_id] = task

    return {
        "scan_id": scan_id,
        "container_id": container_id,
        "container_name": container_name,
        "status": "running",
    }


async def stop_scan(
    token: str,
    scan_id: str,
) -> dict[str, Any]:
    """Stop recon container and finalize scan."""
    task = _active_sync_tasks.pop(scan_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async with async_session_maker() as db:
        row = await db.execute(
            select(ReconScan).where(ReconScan.id == uuid.UUID(scan_id))
        )
        scan = row.scalar_one_or_none()
        if not scan:
            return {"error": "Scan not found"}

        if scan.container_id:
            await _remove_container(token, scan.container_id)

        scan.is_running = False
        scan.stopped_at = datetime.now(timezone.utc)
        scan.container_id = None
        await db.commit()

        scan_dir = Path(scan.recon_json_path).parent if scan.recon_json_path else None
        if scan_dir:
            await _sync_recon_json(scan_id, scan_dir)

    return {"scan_id": scan_id, "status": "stopped"}


async def get_scan_status(scan_id: str) -> dict[str, Any] | None:
    """Get scan status from DB."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(ReconScan).where(ReconScan.id == uuid.UUID(scan_id))
        )
        scan = row.scalar_one_or_none()
        if not scan:
            return None
        return {
            "scan_id": str(scan.id),
            "project_id": scan.project_id,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "stopped_at": scan.stopped_at.isoformat() if scan.stopped_at else None,
            "is_running": scan.is_running,
            "scan_mode": scan.scan_mode,
            "scan_duration": (scan.parameters or {}).get("scan_duration") if isinstance(scan.parameters, dict) else None,
            "interface": scan.interface,
            "bands": scan.bands,
            "ap_count": scan.ap_count,
            "sta_count": scan.sta_count,
            "container_id": scan.container_id,
        }


async def list_scans(project_id: int) -> list[dict[str, Any]]:
    """List all scans for a project."""
    async with async_session_maker() as db:
        rows = await db.execute(
            select(ReconScan)
            .where(ReconScan.project_id == project_id)
            .order_by(ReconScan.created_at.desc())
        )
        scans = rows.scalars().all()
        return [
            {
                "scan_id": str(s.id),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
                "is_running": s.is_running,
                "scan_mode": s.scan_mode,
                "scan_duration": (s.parameters or {}).get("scan_duration") if isinstance(s.parameters, dict) else None,
                "interface": s.interface,
                "bands": s.bands,
                "ap_count": s.ap_count,
                "sta_count": s.sta_count,
            }
            for s in scans
        ]


async def get_aps(
    scan_id: str,
    sort_by: str = "power",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    band: str | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """Get AP list for a scan with pagination and sorting.

    Optional filters:
    - band: "2.4" or "5" - server-side band filtering
    - project_id: used to apply project-level MAC whitelist/blacklist
    """
    allowed_sorts = {
        "bssid", "essid", "channel", "power", "beacons", "privacy",
        "first_seen", "last_seen", "client_count", "band", "speed",
    }
    if sort_by not in allowed_sorts:
        sort_by = "power"

    async with async_session_maker() as db:
        filters = [ReconAP.scan_id == uuid.UUID(scan_id)]

        if band:
            filters.append(ReconAP.band == band)

        if project_id is not None:
            from app.models.project import Project
            proj_row = await db.execute(select(Project).where(Project.id == project_id))
            proj = proj_row.scalar_one_or_none()
            if proj and proj.mac_filter_type and proj.mac_filter_entries:
                macs = [m.upper() for m in proj.mac_filter_entries]
                if proj.mac_filter_type == "whitelist":
                    filters.append(ReconAP.bssid.in_(macs))
                elif proj.mac_filter_type == "blacklist":
                    filters.append(ReconAP.bssid.notin_(macs))

        count_q = select(text("count(*)")).select_from(ReconAP).where(*filters)
        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        col = getattr(ReconAP, sort_by, ReconAP.power)
        order = col.desc() if sort_dir == "desc" else col.asc()
        if sort_by == "power":
            order = col.desc().nullslast() if sort_dir == "desc" else col.asc().nullslast()

        q = (
            select(ReconAP)
            .where(*filters)
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        rows = await db.execute(q)
        aps = rows.scalars().all()

        return {
            "total": total,
            "items": [_ap_to_dict(ap) for ap in aps],
        }


async def get_stas(
    scan_id: str,
    sort_by: str = "power",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    bssid: str | None = None,
) -> dict[str, Any]:
    """Get STA list for a scan with optional BSSID filter."""
    async with async_session_maker() as db:
        base = select(ReconSTA).where(ReconSTA.scan_id == uuid.UUID(scan_id))
        if bssid:
            base = base.where(ReconSTA.associated_bssid == bssid.upper())

        count_q = select(text("count(*)")).select_from(
            base.subquery()
        )
        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        allowed_sorts = {"mac", "power", "packets", "first_seen", "last_seen"}
        if sort_by not in allowed_sorts:
            sort_by = "power"
        col = getattr(ReconSTA, sort_by, ReconSTA.power)
        order = col.desc() if sort_dir == "desc" else col.asc()

        q = base.order_by(order).limit(limit).offset(offset)
        rows = await db.execute(q)
        stas = rows.scalars().all()

        return {
            "total": total,
            "items": [_sta_to_dict(sta) for sta in stas],
        }


async def get_ap_detail(scan_id: str, bssid: str) -> dict[str, Any] | None:
    """Get detailed AP info including clients."""
    async with async_session_maker() as db:
        row = await db.execute(
            select(ReconAP).where(
                ReconAP.scan_id == uuid.UUID(scan_id),
                ReconAP.bssid == bssid.upper(),
            )
        )
        ap = row.scalar_one_or_none()
        if not ap:
            return None

        sta_rows = await db.execute(
            select(ReconSTA).where(
                ReconSTA.scan_id == uuid.UUID(scan_id),
                ReconSTA.associated_bssid == bssid.upper(),
            )
        )
        clients = sta_rows.scalars().all()

        ap_dict = _ap_to_dict(ap)
        ap_dict["clients"] = [_sta_to_dict(c) for c in clients]
        return ap_dict


# ---------------------------------------------------------------------------
# Container cleanup
# ---------------------------------------------------------------------------

RECON_STOP_TIMEOUT = 30

async def _remove_container(
    token: str | None,
    container_id: str | None,
    stop_timeout: int = RECON_STOP_TIMEOUT,
) -> None:
    """Stop + remove a recon container. Best-effort, errors are logged."""
    if not token or not container_id:
        return
    try:
        await tool_manager_client.tool_manager_stop_container(
            token=token,
            container_id=container_id,
            remove=True,
            stop_timeout=stop_timeout,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Background sync loop
# ---------------------------------------------------------------------------

async def _sync_loop(
    scan_id: str,
    scan_dir: Path,
    *,
    token: str | None = None,
    container_id: str | None = None,
) -> None:
    """Periodically read recon.json and upsert into DB.

    Also monitors status.json written by the recon container to detect when a
    timed scan completes on its own (without the user pressing Stop).
    When the scan finishes, the exited container is removed.
    """
    scan_uuid = uuid.UUID(scan_id)
    try:
        while True:
            await asyncio.sleep(SYNC_INTERVAL)
            await _sync_recon_json(scan_id, scan_dir)

            # Check if the container reported completion via status.json
            status_path = scan_dir / "status.json"
            if status_path.exists():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    status = {}

                if not status.get("is_running", True):
                    async with async_session_maker() as db:
                        await db.execute(
                            update(ReconScan)
                            .where(ReconScan.id == scan_uuid)
                            .values(
                                is_running=False,
                                stopped_at=_parse_ts(status.get("stopped_at"))
                                or datetime.now(timezone.utc),
                                container_id=None,
                            )
                        )
                        await db.commit()
                    await _remove_container(token, container_id)
                    break

            # Also respect manual stop_scan() which sets is_running=False in DB
            async with async_session_maker() as db:
                row = await db.execute(
                    select(ReconScan.is_running).where(ReconScan.id == scan_uuid)
                )
                is_running = row.scalar_one_or_none()
                if is_running is False:
                    break
    except asyncio.CancelledError:
        await _sync_recon_json(scan_id, scan_dir)
    finally:
        _active_sync_tasks.pop(scan_id, None)


async def _sync_recon_json(scan_id: str, scan_dir: Path) -> None:
    """Read recon.json and upsert AP/STA records."""
    recon_path = scan_dir / "recon.json"
    if not recon_path.exists():
        return

    try:
        data = json.loads(recon_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    aps = data.get("aps", [])
    stats = data.get("stats", {})

    all_stas: list[dict] = data.get("stas", [])
    if not all_stas:
        # Fallback for older recon.json without top-level "stas"
        all_stas = list(data.get("unassociated_stas", []))
        for ap in aps:
            for client_mac in ap.get("clients", []):
                existing = next((s for s in all_stas if s.get("mac") == client_mac), None)
                if not existing:
                    all_stas.append({
                        "mac": client_mac,
                        "associated_bssid": ap["bssid"],
                        "power": None,
                        "packets": 0,
                        "probed_essids": [],
                        "first_seen": None,
                        "last_seen": None,
                    })

    scan_uuid = uuid.UUID(scan_id)

    async with async_session_maker() as db:
        await _upsert_aps(db, scan_uuid, aps)
        await _upsert_stas(db, scan_uuid, all_stas)

        await db.execute(
            select(ReconScan)
            .where(ReconScan.id == scan_uuid)
            .with_for_update()
        )
        await db.execute(
            update(ReconScan)
            .where(ReconScan.id == scan_uuid)
            .values(
                ap_count=stats.get("ap_count", len(aps)),
                sta_count=stats.get("sta_count", len(all_stas)),
            )
        )
        await db.commit()


async def _upsert_aps(db: AsyncSession, scan_id: uuid.UUID, aps: list[dict]) -> None:
    if not aps:
        return

    for ap in aps:
        values = {
            "scan_id": scan_id,
            "bssid": ap["bssid"],
            "essid": ap.get("essid"),
            "is_hidden": ap.get("is_hidden", False),
            "channel": ap.get("channel"),
            "band": ap.get("band"),
            "power": ap.get("power"),
            "speed": ap.get("speed"),
            "privacy": ap.get("privacy"),
            "cipher": ap.get("cipher"),
            "auth": ap.get("auth"),
            "beacons": ap.get("beacons", 0),
            "data_frames": ap.get("data_frames", 0),
            "iv_count": ap.get("iv_count", 0),
            "wps": ap.get("wps"),
            "security_info": ap.get("security_info"),
            "tagged_params": ap.get("tagged_params"),
            "first_seen": _parse_ts(ap.get("first_seen")),
            "last_seen": _parse_ts(ap.get("last_seen")),
            "client_count": ap.get("client_count", 0),
        }

        stmt = pg_insert(ReconAP).values(**values)
        update_cols = {k: v for k, v in values.items() if k not in ("scan_id", "bssid")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["scan_id", "bssid"],
            set_=update_cols,
        )
        await db.execute(stmt)


async def _upsert_stas(db: AsyncSession, scan_id: uuid.UUID, stas: list[dict]) -> None:
    if not stas:
        return

    for sta in stas:
        values = {
            "scan_id": scan_id,
            "mac": sta["mac"],
            "power": sta.get("power"),
            "packets": sta.get("packets", 0),
            "probed_essids": sta.get("probed_essids", []),
            "associated_bssid": sta.get("associated_bssid"),
            "first_seen": _parse_ts(sta.get("first_seen")),
            "last_seen": _parse_ts(sta.get("last_seen")),
        }

        stmt = pg_insert(ReconSTA).values(**values)
        update_cols = {k: v for k, v in values.items() if k not in ("scan_id", "mac")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["scan_id", "mac"],
            set_=update_cols,
        )
        await db.execute(stmt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


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


def _sta_to_dict(sta: ReconSTA) -> dict[str, Any]:
    return {
        "mac": sta.mac,
        "power": sta.power,
        "packets": sta.packets,
        "probed_essids": sta.probed_essids,
        "associated_bssid": sta.associated_bssid,
        "first_seen": sta.first_seen.isoformat() if sta.first_seen else None,
        "last_seen": sta.last_seen.isoformat() if sta.last_seen else None,
    }


async def shutdown_all_sync_tasks() -> None:
    """Cancel all active sync tasks (call on app shutdown)."""
    for scan_id, task in _active_sync_tasks.items():
        if not task.done():
            task.cancel()
    for task in _active_sync_tasks.values():
        try:
            await task
        except asyncio.CancelledError:
            pass
    _active_sync_tasks.clear()
