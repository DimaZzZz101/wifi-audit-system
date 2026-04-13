"""Add unique constraint on audit_session.name

Revision ID: 004
Revises: 003
Create Date: 2026-03-10

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Переименовываем дубликаты перед добавлением unique constraint
    rows = conn.execute(
        text("""
            SELECT name, array_agg(id ORDER BY id) as ids
            FROM audit_session
            GROUP BY name
            HAVING count(*) > 1
        """)
    ).fetchall()
    for name, ids in rows:
        id_list = list(ids) if hasattr(ids, "__iter__") and not isinstance(ids, str) else [ids]
        for i, sid in enumerate(id_list):
            if i > 0:
                for attempt in range(1, 100):
                    new_name = f"{name} ({attempt})"[:256]
                    exists = conn.execute(
                        text("SELECT 1 FROM audit_session WHERE name = :n AND id != :id"),
                        {"n": new_name, "id": sid},
                    ).fetchone()
                    if not exists:
                        conn.execute(text("UPDATE audit_session SET name = :n WHERE id = :id"), {"n": new_name, "id": sid})
                        break
    op.create_unique_constraint(
        "uq_audit_session_name",
        "audit_session",
        ["name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_audit_session_name", "audit_session", type_="unique")
