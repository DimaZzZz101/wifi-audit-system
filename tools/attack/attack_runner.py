"""Unified attack dispatcher. Reads ATTACK_TYPE and ATTACK_CONFIG from env,
dispatches to the appropriate handler module. Handles graceful stop via SIGTERM."""
from __future__ import annotations

import importlib
import json
import os
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("ATTACK_DATA_DIR", "/data/attack"))
STOP_FLAG = DATA_DIR / ".stop_requested"

_stop_requested = False


def _handle_sigterm(signum, frame):
    global _stop_requested
    _stop_requested = True
    STOP_FLAG.write_text("1")


def is_stop_requested() -> bool:
    return _stop_requested or STOP_FLAG.exists()


def _write_status(status: str, progress: str = "", error: str = "") -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        payload["error"] = error
    if status in ("completed", "failed", "stopped"):
        payload["stopped_at"] = datetime.now(timezone.utc).isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


HANDLER_MAP = {
    "deauth": "handlers.deauth",
    "handshake_capture": "handlers.handshake_capture",
    "pmkid_capture": "handlers.pmkid_capture",
    "wps_pixie": "handlers.wps_pixie",
    "dragonshift": "handlers.dragonshift",
    "psk_crack": "handlers.psk_crack",
    "dos": "handlers.dos",
}


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    attack_type = os.environ.get("ATTACK_TYPE", "").strip()
    config_raw = os.environ.get("ATTACK_CONFIG", "{}").strip()
    os.environ["_RUNNER_STARTED_AT"] = datetime.now(timezone.utc).isoformat()

    try:
        config = json.loads(config_raw)
    except json.JSONDecodeError as e:
        _write_status("failed", error=f"Invalid ATTACK_CONFIG JSON: {e}")
        sys.exit(1)

    module_name = HANDLER_MAP.get(attack_type)
    if not module_name:
        _write_status("failed", error=f"Unknown attack type: {attack_type}")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()

    _write_status("running", progress="initializing")

    try:
        handler = importlib.import_module(module_name)
        handler.run(config, DATA_DIR)
        final_status = "stopped" if is_stop_requested() else "completed"
        _write_status(final_status, progress="done")
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        _write_status("failed", error=tb[-2000:])
        sys.exit(1)


if __name__ == "__main__":
    main()
