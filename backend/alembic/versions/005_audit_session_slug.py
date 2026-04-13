"""Add slug column to audit_session - уникальная строка для пути к файлам

Revision ID: 005
Revises: 004
Create Date: 2026-03-10

"""
import os
import secrets
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_session", sa.Column("slug", sa.String(32), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(text("SELECT id FROM audit_session")).fetchall()
    base_dir = Path(os.environ.get("ARTIFACTS_DIR", "/data/artifacts")) / "sessions"
    for row in rows:
        sid = row[0]
        slug = secrets.token_hex(6)
        conn.execute(text("UPDATE audit_session SET slug = :s WHERE id = :id"), {"s": slug, "id": sid})
        old_path = base_dir / str(sid)
        new_path = base_dir / slug
        if old_path.exists() and not new_path.exists():
            try:
                old_path.rename(new_path)
            except OSError:
                pass
    op.alter_column("audit_session", "slug", nullable=False)
    op.create_unique_constraint("uq_audit_session_slug", "audit_session", ["slug"])
    op.create_index("ix_audit_session_slug", "audit_session", ["slug"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_session_slug", table_name="audit_session")
    op.drop_constraint("uq_audit_session_slug", "audit_session", type_="unique")
    op.drop_column("audit_session", "slug")
