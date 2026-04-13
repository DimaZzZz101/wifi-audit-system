"""Recon tables: recon_scan, recon_ap, recon_sta

Revision ID: 006
Revises: 005
Create Date: 2026-03-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recon_scan",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("audit_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("scan_mode", sa.String(16), nullable=False, server_default="continuous"),
        sa.Column("interface", sa.String(64), nullable=False),
        sa.Column("bands", sa.String(16), server_default="abg"),
        sa.Column("parameters", JSONB, server_default="{}"),
        sa.Column("container_id", sa.String(128), nullable=True),
        sa.Column("recon_json_path", sa.String(512), nullable=True),
        sa.Column("pcap_path", sa.String(512), nullable=True),
        sa.Column("ap_count", sa.Integer(), server_default="0"),
        sa.Column("sta_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_recon_scan_session", "recon_scan", ["session_id"])

    op.create_table(
        "recon_ap",
        sa.Column("scan_id", UUID(as_uuid=True), sa.ForeignKey("recon_scan.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bssid", sa.String(17), nullable=False),
        sa.Column("essid", sa.String(256), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column("band", sa.String(4), nullable=True),
        sa.Column("power", sa.Integer(), nullable=True),
        sa.Column("speed", sa.Integer(), nullable=True),
        sa.Column("privacy", sa.String(64), nullable=True),
        sa.Column("cipher", sa.String(64), nullable=True),
        sa.Column("auth", sa.String(64), nullable=True),
        sa.Column("beacons", sa.Integer(), server_default="0"),
        sa.Column("data_frames", sa.Integer(), server_default="0"),
        sa.Column("iv_count", sa.Integer(), server_default="0"),
        sa.Column("wps", JSONB, nullable=True),
        sa.Column("security_info", JSONB, nullable=True),
        sa.Column("tagged_params", JSONB, nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_count", sa.Integer(), server_default="0"),
        sa.PrimaryKeyConstraint("scan_id", "bssid"),
    )

    op.create_table(
        "recon_sta",
        sa.Column("scan_id", UUID(as_uuid=True), sa.ForeignKey("recon_scan.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("power", sa.Integer(), nullable=True),
        sa.Column("packets", sa.Integer(), server_default="0"),
        sa.Column("probed_essids", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("associated_bssid", sa.String(17), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("scan_id", "mac"),
    )


def downgrade() -> None:
    op.drop_table("recon_sta")
    op.drop_table("recon_ap")
    op.drop_index("ix_recon_scan_session", table_name="recon_scan")
    op.drop_table("recon_scan")
