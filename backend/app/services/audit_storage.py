"""Helpers for audit artifact directory names and UI labels."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def _slugify(value: str, max_len: int = 32) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-_.").lower()
    if not normalized:
        return ""
    return normalized[:max_len]


def build_audit_storage_dirname(
    *,
    plan_id: Any,
    created_at: datetime | None,
    essid: str | None,
    bssid: str | None,
) -> str:
    short_id = str(plan_id).split("-")[0]
    ts = (created_at or datetime.utcnow()).strftime("%Y%m%d-%H%M%S")
    target = _slugify((essid or "").strip(), max_len=28)
    if not target and bssid:
        target = bssid.replace(":", "-").lower()
    parts = [ts]
    if target:
        parts.append(target)
    parts.append(short_id)
    return "_".join(parts)


def build_audit_display_name(
    *,
    plan_id: Any,
    created_at: datetime | None,
    essid: str | None,
    bssid: str | None,
) -> str:
    short_id = str(plan_id).split("-")[0]
    ts = (created_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M")
    target = (essid or "").strip() or (bssid or "").upper() or "unknown-ap"
    return f"{ts} | {target} | {short_id}"
