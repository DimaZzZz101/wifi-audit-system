"""Audit API: plan lifecycle, job management, attack execution."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_bearer_token, require_user, audit
from app.models.user import User
from app.models.project import Project
from app.schemas.audit import (
    AuditJobResponse,
    AuditJobUpdate,
    AuditPlanCreate,
    AuditPlanListItem,
    AuditPlanResponse,
)
from app.services import audit_service, attack_service

router = APIRouter(prefix="/projects/{project_id}/audit", tags=["audit"])


async def _get_project(project_id: int, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


# --- Plans ---

@router.post("/plan", response_model=AuditPlanResponse, summary="Create audit plan (runs B&B)")
async def create_plan(
    project_id: int,
    body: AuditPlanCreate,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> AuditPlanResponse:
    project = await _get_project(project_id, db)
    try:
        plan = await audit_service.create_audit_plan(
            project_id=project.id,
            bssid=body.bssid,
            scan_id=body.scan_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await audit(db, user_id=current_user.id, action="audit.plan.create", request=request,
                resource_type="project", resource_id=str(project_id),
                details={"plan_id": plan["id"], "bssid": body.bssid})
    return AuditPlanResponse(**plan)


@router.get("/plans", response_model=list[AuditPlanListItem], summary="List audit plans")
async def list_plans(
    project_id: int,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[AuditPlanListItem]:
    await _get_project(project_id, db)
    plans = await audit_service.list_audit_plans(project_id)
    return [AuditPlanListItem(**p) for p in plans]


@router.get("/plans/{plan_id}", response_model=AuditPlanResponse, summary="Get plan with jobs")
async def get_plan(
    project_id: int,
    plan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AuditPlanResponse:
    await _get_project(project_id, db)
    try:
        plan = await audit_service.get_audit_plan(plan_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return AuditPlanResponse(**plan)


@router.post("/plans/{plan_id}/start", summary="Start plan execution")
async def start_plan(
    project_id: int,
    plan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    await _get_project(project_id, db)
    try:
        result = await audit_service.start_plan(plan_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return result


@router.delete("/plans/{plan_id}", summary="Delete/cancel plan")
async def delete_plan(
    project_id: int,
    plan_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    await _get_project(project_id, db)
    await audit_service.delete_audit_plan(plan_id)
    await audit(db, user_id=current_user.id, action="audit.plan.delete", request=request,
                resource_type="project", resource_id=str(project_id),
                details={"plan_id": plan_id})
    return {"ok": True}


# --- Jobs ---

@router.get("/jobs/{job_id}", response_model=AuditJobResponse, summary="Get job detail")
async def get_job(
    project_id: int,
    job_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AuditJobResponse:
    await _get_project(project_id, db)
    job = await audit_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return AuditJobResponse(**job)


@router.patch("/jobs/{job_id}", response_model=AuditJobResponse, summary="Update job config")
async def update_job(
    project_id: int,
    job_id: str,
    body: AuditJobUpdate,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AuditJobResponse:
    await _get_project(project_id, db)
    try:
        job = await audit_service.update_job(job_id, config=body.config, interface=body.interface)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return AuditJobResponse(**job)


@router.post("/jobs/{job_id}/start", summary="Start attack job")
async def start_job(
    project_id: int,
    job_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    project = await _get_project(project_id, db)
    token = get_bearer_token(request)

    plan_data = await audit_service.get_job(job_id)
    if not plan_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    try:
        result = await attack_service.start_job(
            token=token,
            job_id=job_id,
            project_slug=project.slug,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    await audit(db, user_id=current_user.id, action="audit.job.start", request=request,
                resource_type="project", resource_id=str(project_id),
                details={"job_id": job_id})
    return result


@router.post("/jobs/{job_id}/stop", summary="Stop running job")
async def stop_job(
    project_id: int,
    job_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    project = await _get_project(project_id, db)
    token = get_bearer_token(request)
    result = await attack_service.stop_job(token=token, job_id=job_id)
    return result


@router.post("/jobs/{job_id}/restart", response_model=AuditJobResponse, summary="Restart completed/failed job")
async def restart_job(
    project_id: int,
    job_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> AuditJobResponse:
    await _get_project(project_id, db)
    try:
        job = await attack_service.restart_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AuditJobResponse(**job)


@router.post("/jobs/{job_id}/skip", summary="Skip job")
async def skip_job(
    project_id: int,
    job_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AuditJobResponse:
    await _get_project(project_id, db)
    try:
        job = await audit_service.skip_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return AuditJobResponse(**job)
