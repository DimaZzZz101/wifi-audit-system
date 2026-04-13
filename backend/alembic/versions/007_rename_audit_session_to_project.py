"""Rename audit_session table to project, update FK in recon_scan

Revision ID: 007
Revises: 006
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE recon_scan DROP CONSTRAINT IF EXISTS recon_scan_session_id_fkey")
    op.rename_table("audit_session", "project")
    op.alter_column("recon_scan", "session_id", new_column_name="project_id")
    op.create_foreign_key(
        "recon_scan_project_id_fkey",
        "recon_scan",
        "project",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recon_scan DROP CONSTRAINT IF EXISTS recon_scan_project_id_fkey")
    op.alter_column("recon_scan", "project_id", new_column_name="session_id")
    op.rename_table("project", "audit_session")
    op.create_foreign_key(
        "recon_scan_session_id_fkey",
        "recon_scan",
        "audit_session",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
