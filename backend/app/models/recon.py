"""Recon models: scan, access point, station."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReconScan(Base):
    __tablename__ = "recon_scan"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_running: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    scan_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="continuous")
    interface: Mapped[str] = mapped_column(String(64), nullable=False)
    bands: Mapped[str] = mapped_column(String(16), server_default="abg")
    parameters: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recon_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pcap_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ap_count: Mapped[int] = mapped_column(Integer, server_default="0")
    sta_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReconAP(Base):
    __tablename__ = "recon_ap"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recon_scan.id", ondelete="CASCADE"), primary_key=True
    )
    bssid: Mapped[str] = mapped_column(String(17), primary_key=True)
    essid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    channel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band: Mapped[str | None] = mapped_column(String(4), nullable=True)
    power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    privacy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cipher: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth: Mapped[str | None] = mapped_column(String(64), nullable=True)
    beacons: Mapped[int] = mapped_column(Integer, server_default="0")
    data_frames: Mapped[int] = mapped_column(Integer, server_default="0")
    iv_count: Mapped[int] = mapped_column(Integer, server_default="0")
    wps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    security_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tagged_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_count: Mapped[int] = mapped_column(Integer, server_default="0")


class ReconSTA(Base):
    __tablename__ = "recon_sta"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recon_scan.id", ondelete="CASCADE"), primary_key=True
    )
    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    packets: Mapped[int] = mapped_column(Integer, server_default="0")
    probed_essids: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    associated_bssid: Mapped[str | None] = mapped_column(String(17), nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
