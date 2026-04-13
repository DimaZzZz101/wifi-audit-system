"""Audit session table - сессии аудита Wi-Fi

Revision ID: 003
Revises: 002
Create Date: 2026-03-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_session",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("session_type", sa.String(64), nullable=False, server_default="audit"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_session_status"), "audit_session", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_session_status"), table_name="audit_session")
    op.drop_table("audit_session")
