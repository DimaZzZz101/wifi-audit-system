"""Registry image table - реестр образов WiFi Audit

Revision ID: 002
Revises: 001
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registry_image",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("image_reference", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_registry_image_image_reference"), "registry_image", ["image_reference"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_registry_image_image_reference"), table_name="registry_image")
    op.drop_table("registry_image")
