"""Pydantic schemas for recon (scan, AP, STA)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReconStartRequest(BaseModel):
    interface: str = Field(..., min_length=1, description="Wi-Fi interface in monitor mode")
    scan_mode: str = Field("continuous", pattern="^(continuous|timed)$")
    scan_duration: int | None = Field(None, ge=5, description="Duration in seconds (timed mode)")
    bands: str = Field("abg", pattern="^[abg]{1,3}$")
    channels: str | None = Field(None, description="Comma-separated channel list")


class ReconScanResponse(BaseModel):
    scan_id: str
    started_at: str | None = None
    stopped_at: str | None = None
    is_running: bool = False
    scan_mode: str = "continuous"
    scan_duration: int | None = None
    interface: str = ""
    bands: str = "abg"
    ap_count: int = 0
    sta_count: int = 0
    container_id: str | None = None


class ReconStartResponse(BaseModel):
    scan_id: str
    container_id: str | None = None
    container_name: str | None = None
    status: str = "running"


class ReconStopResponse(BaseModel):
    scan_id: str
    status: str = "stopped"
    error: str | None = None


class WPSInfo(BaseModel):
    """WPS-метаданные; model_* - осмысленные имена полей, не конфликт с BaseModel."""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = False
    configured: bool = False
    version: str | None = None
    locked: bool = False
    device_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    model_number: str | None = None
    serial_number: str | None = None


class SecurityInfo(BaseModel):
    encryption: str = "Open"
    display_security: str | None = None
    cipher: str = ""
    akm: str = ""
    pmf: str = "none"
    wps_enabled: bool = False
    wps_locked: bool = False
    vulnerabilities: list[str] = []


class APResponse(BaseModel):
    bssid: str
    essid: str | None = None
    is_hidden: bool = False
    channel: int | None = None
    band: str | None = None
    power: int | None = None
    speed: int | None = None
    privacy: str | None = None
    cipher: str | None = None
    auth: str | None = None
    beacons: int = 0
    data_frames: int = 0
    iv_count: int = 0
    wps: dict | None = None
    security_info: dict | None = None
    tagged_params: dict | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    client_count: int = 0
    clients: list[dict] | None = None


class STAResponse(BaseModel):
    mac: str
    power: int | None = None
    packets: int = 0
    probed_essids: list[str] = []
    associated_bssid: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class PaginatedAPResponse(BaseModel):
    total: int = 0
    items: list[APResponse] = []


class PaginatedSTAResponse(BaseModel):
    total: int = 0
    items: list[STAResponse] = []
