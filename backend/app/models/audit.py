"""Audit models: AuditPlan, AuditJob."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditPlan(Base):
    __tablename__ = "audit_plan"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bssid: Mapped[str] = mapped_column(String(17), nullable=False)
    essid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ap_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    time_budget_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_solution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditJob(Base):
    __tablename__ = "audit_job"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    audit_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attack_type: Mapped[str] = mapped_column(String(32), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_paths: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
