"""Add audit_plan, audit_job, dictionary, system_settings tables

Revision ID: 009
Revises: 008
Create Date: 2026-04-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_plan",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("bssid", sa.String(17), nullable=False),
        sa.Column("essid", sa.String(256), nullable=True),
        sa.Column("ap_snapshot", JSONB, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("time_budget_s", sa.Integer(), nullable=True),
        sa.Column("bb_solution", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "audit_job",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("audit_plan_id", UUID(as_uuid=True), sa.ForeignKey("audit_plan.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attack_type", sa.String(32), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("container_id", sa.String(128), nullable=True),
        sa.Column("interface", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("log_path", sa.String(512), nullable=True),
        sa.Column("artifact_paths", JSONB, nullable=True),
    )

    op.create_table(
        "dictionary",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0"),
        sa.Column("word_count", sa.BigInteger(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_table("dictionary")
    op.drop_table("audit_job")
    op.drop_table("audit_plan")
