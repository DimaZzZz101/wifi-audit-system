"""Add mac_filter_type, mac_filter_entries, obfuscation_enabled to project

Revision ID: 008
Revises: 007
Create Date: 2026-04-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("mac_filter_type", sa.String(16), nullable=True))
    op.add_column("project", sa.Column("mac_filter_entries", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("project", sa.Column("obfuscation_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("project", "obfuscation_enabled")
    op.drop_column("project", "mac_filter_entries")
    op.drop_column("project", "mac_filter_type")
