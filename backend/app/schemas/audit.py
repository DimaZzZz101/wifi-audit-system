"""Pydantic schemas for audit plans, jobs, and settings."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Audit Plan ---

class AuditPlanCreate(BaseModel):
    bssid: str = Field(..., min_length=17, max_length=17)
    scan_id: str = Field(..., min_length=1)


class AuditJobResponse(BaseModel):
    id: str
    audit_plan_id: str
    attack_type: str
    order_index: int
    status: str = "pending"
    config: dict = {}
    container_id: str | None = None
    interface: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    result: dict | None = None
    log_path: str | None = None
    artifact_paths: dict | None = None


class AuditPlanResponse(BaseModel):
    id: str
    project_id: int
    scan_id: str | None = None
    bssid: str
    essid: str | None = None
    status: str = "pending"
    time_budget_s: int | None = None
    bb_solution: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None
    jobs: list[AuditJobResponse] = []


class AuditPlanListItem(BaseModel):
    id: str
    bssid: str
    essid: str | None = None
    status: str = "pending"
    time_budget_s: int | None = None
    created_at: str | None = None
    job_count: int = 0


# --- Job config update ---

class AuditJobUpdate(BaseModel):
    config: dict | None = None
    interface: str | None = None


# --- Audit settings ---

class AttackParamItem(BaseModel):
    name: str
    weight: float = Field(ge=0.0, le=1.0)
    time_s: float = Field(ge=0.0)


class AuditSettingsResponse(BaseModel):
    attacks: list[AttackParamItem] = []
    time_budget_s: float = 28800.0


class AuditSettingsUpdate(BaseModel):
    attacks: list[AttackParamItem] | None = None
    time_budget_s: float | None = None
