"""Recon API: scan lifecycle + AP/STA data access."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_bearer_token, require_user, audit
from app.models.user import User
from app.models.project import Project
from app.schemas.recon import (
    APResponse,
    PaginatedAPResponse,
    PaginatedSTAResponse,
    ReconScanResponse,
    ReconStartRequest,
    ReconStartResponse,
    ReconStopResponse,
    STAResponse,
)
from app.services import recon_service

router = APIRouter(prefix="/projects/{project_id}/recon", tags=["recon"])


async def _get_active_project(
    project_id: int,
    db: AsyncSession,
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post(
    "/start",
    response_model=ReconStartResponse,
    summary="Start recon scan",
)
async def recon_start(
    project_id: int,
    request: Request,
    body: ReconStartRequest,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ReconStartResponse:
    project = await _get_active_project(project_id, db)
    if project.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project must be active to start scanning.",
        )

    token = get_bearer_token(request)
    try:
        result = await recon_service.start_scan(
            token=token,
            project_id=project.id,
            slug=project.slug,
            interface=body.interface,
            scan_mode=body.scan_mode,
            scan_duration=body.scan_duration,
            bands=body.bands,
            channels=body.channels,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to start scan: {e}",
        )

    await audit(
        db,
        user_id=current_user.id,
        action="recon.start",
        request=request,
        resource_type="project",
        resource_id=str(project_id),
        details={"scan_id": result["scan_id"], "interface": body.interface, "scan_mode": body.scan_mode},
    )

    return ReconStartResponse(**result)


@router.post(
    "/{scan_id}/stop",
    response_model=ReconStopResponse,
    summary="Stop recon scan",
)
async def recon_stop(
    project_id: int,
    scan_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ReconStopResponse:
    await _get_active_project(project_id, db)
    token = get_bearer_token(request)

    try:
        result = await recon_service.stop_scan(token=token, scan_id=scan_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to stop scan: {e}",
        )

    await audit(
        db,
        user_id=current_user.id,
        action="recon.stop",
        request=request,
        resource_type="project",
        resource_id=str(project_id),
        details={"scan_id": scan_id},
    )

    return ReconStopResponse(**result)


@router.get(
    "/scans",
    response_model=list[ReconScanResponse],
    summary="List scans for session",
)
async def recon_scans_list(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReconScanResponse]:
    project = await _get_active_project(project_id, db)
    scans = await recon_service.list_scans(project.id)
    return [ReconScanResponse(**s) for s in scans]


@router.get(
    "/{scan_id}/status",
    response_model=ReconScanResponse,
    summary="Get scan status",
)
async def recon_scan_status(
    project_id: int,
    scan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ReconScanResponse:
    await _get_active_project(project_id, db)
    scan_status = await recon_service.get_scan_status(scan_id)
    if not scan_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    return ReconScanResponse(**scan_status)


@router.get(
    "/{scan_id}/aps",
    response_model=PaginatedAPResponse,
    summary="Get access points for scan",
)
async def recon_aps(
    project_id: int,
    scan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    sort_by: str = Query("power", description="Column to sort by"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    band: str | None = Query(None, description="Filter by band: 2.4 or 5"),
) -> PaginatedAPResponse:
    await _get_active_project(project_id, db)
    data = await recon_service.get_aps(
        scan_id=scan_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        band=band,
        project_id=project_id,
    )
    return PaginatedAPResponse(**data)


@router.get(
    "/{scan_id}/stas",
    response_model=PaginatedSTAResponse,
    summary="Get stations for scan",
)
async def recon_stas(
    project_id: int,
    scan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    sort_by: str = Query("power", description="Column to sort by"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    bssid: str | None = Query(None, description="Filter by associated BSSID"),
) -> PaginatedSTAResponse:
    await _get_active_project(project_id, db)
    data = await recon_service.get_stas(
        scan_id=scan_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        bssid=bssid,
    )
    return PaginatedSTAResponse(**data)


@router.get(
    "/{scan_id}/aps/{bssid}",
    response_model=APResponse,
    summary="Get AP detail with clients",
)
async def recon_ap_detail(
    project_id: int,
    scan_id: str,
    bssid: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> APResponse:
    await _get_active_project(project_id, db)
    detail = await recon_service.get_ap_detail(scan_id=scan_id, bssid=bssid)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AP not found")
    return APResponse(**detail)
