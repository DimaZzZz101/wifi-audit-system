"""Audit settings API: attack weights, times, global time budget."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.models.user import User
from app.schemas.audit import AuditSettingsResponse, AuditSettingsUpdate
from app.services import audit_service

router = APIRouter(prefix="/settings/audit", tags=["settings"])


@router.get("/", response_model=AuditSettingsResponse, summary="Get audit attack parameters")
async def get_settings(
    current_user: Annotated[User, Depends(require_user)],
) -> AuditSettingsResponse:
    data = await audit_service.get_audit_settings()
    return AuditSettingsResponse(**data)


@router.put("/", response_model=AuditSettingsResponse, summary="Update audit attack parameters")
async def update_settings(
    body: AuditSettingsUpdate,
    current_user: Annotated[User, Depends(require_user)],
) -> AuditSettingsResponse:
    current = await audit_service.get_audit_settings()
    if body.attacks is not None:
        current["attacks"] = [a.model_dump() for a in body.attacks]
    if body.time_budget_s is not None:
        current["time_budget_s"] = body.time_budget_s
    data = await audit_service.update_settings(current)
    return AuditSettingsResponse(**data)
