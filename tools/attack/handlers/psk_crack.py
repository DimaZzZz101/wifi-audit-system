"""PSK cracking handler: aircrack-ng (default) or hashcat (CPU-only).
Reads handshake/PMKID from /data/capture (mounted from source job) or /data/attack."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from _log_util import log, ToolOutputLogger, drain_stdout, drain_stdout_cr

STATUS_INTERVAL = 10

AIRCRACK_IMPORTANT_RE = [
    re.compile(r"KEY FOUND", re.I),
    re.compile(r"Passphrase not in", re.I),
    re.compile(r"keys tested", re.I),
    re.compile(r"ESSID is required", re.I),
]

HASHCAT_IMPORTANT_RE = [
    re.compile(r"Recovered", re.I),
    re.compile(r"Cracked", re.I),
    re.compile(r"Status\s*\.\.", re.I),
    re.compile(r"Exhausted", re.I),
]


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def _resolve_capture_file(config: dict, data_dir: Path, tool: str) -> str | None:
    """Find best capture file for the given tool.

    hashcat needs .hc22000; aircrack-ng needs .pcap/.cap.
    """
    capture_mount = Path("/data/capture")

    if tool == "hashcat":
        preferred_keys = ("hc22000",)
        preferred_globs = ("*.hc22000",)
        fallback_globs = ()
    else:
        preferred_keys = ("pcap",)
        preferred_globs = ("handshake.pcap", "*.pcap", "*.cap")
        fallback_globs = ()

    def _find_in(raw: str) -> str | None:
        raw_path = Path(raw)
        if raw_path.exists() and raw_path.stat().st_size > 0:
            return str(raw_path)
        fname = raw_path.name
        for d in (capture_mount, data_dir):
            candidate = d / fname
            if candidate.exists() and candidate.stat().st_size > 0:
                return str(candidate)
        return None

    for key in preferred_keys:
        raw = config.get(key)
        if raw:
            found = _find_in(raw)
            if found:
                return found

    for key in ("hc22000", "pcap"):
        if key in preferred_keys:
            continue
        raw = config.get(key)
        if raw and fallback_globs:
            found = _find_in(raw)
            if found:
                return found

    for search_dir in (capture_mount, data_dir):
        if not search_dir.exists():
            continue
        for pattern in (*preferred_globs, *fallback_globs):
            for f in sorted(search_dir.glob(pattern), key=lambda p: p.stat().st_size, reverse=True):
                if f.stat().st_size > 0:
                    return str(f)
    return None


def _validate_capture_for_tool(capture: str, tool: str) -> tuple[bool, str]:
    capture_path = Path(capture)
    if not capture_path.exists() or capture_path.stat().st_size <= 0:
        return False, "capture file does not exist or is empty"

    if tool == "hashcat":
        if capture_path.suffix.lower() != ".hc22000":
            return False, "hashcat requires .hc22000 input"
        first_line = capture_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not first_line:
            return False, "hc22000 file is empty"
        if "*" not in first_line[0]:
            return False, "invalid hc22000 format"
        return True, ""

    if capture_path.suffix.lower() not in (".pcap", ".cap"):
        return False, "aircrack-ng requires .pcap/.cap input"

    # Ensure tshark can parse the file header before starting a long crack run.
    try:
        r = subprocess.run(
            ["tshark", "-nr", str(capture_path), "-c", "1"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return False, "tshark timed out while checking capture format"
    if r.returncode != 0:
        return False, "capture file is unreadable by tshark (likely invalid pcap format)"
    return True, ""


def _extract_essid_from_capture(capture: str, bssid: str, log_path: Path) -> str:
    """Try to detect ESSID from pcap/cap for aircrack-ng -e fallback."""
    capture_path = Path(capture)
    if capture_path.suffix.lower() not in (".pcap", ".cap"):
        return ""

    filters: list[str] = []
    if bssid:
        bssid_u = bssid.upper()
        filters.extend(
            [
                f'wlan.bssid == {bssid_u} && wlan_mgt.ssid',
                f'wlan.addr == {bssid_u} && wlan_mgt.ssid',
            ]
        )
    filters.append("wlan_mgt.ssid")

    for display_filter in filters:
        try:
            r = subprocess.run(
                [
                    "tshark",
                    "-nr",
                    capture,
                    "-Y",
                    display_filter,
                    "-T",
                    "fields",
                    "-e",
                    "wlan_mgt.ssid",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            continue
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            essid = line.strip()
            if essid:
                log(log_path, f"detected ESSID from capture: {essid}")
                return essid
    return ""


def _hashcat_runtime_available(log_path: Path) -> bool:
    """Check if hashcat runtime is usable before starting cracking."""
    try:
        r = subprocess.run(
            ["hashcat", "-I"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as e:
        log(log_path, f"hashcat runtime probe failed: {e}")
        return False

    output = f"{r.stdout}\n{r.stderr}".lower()
    if r.returncode != 0:
        return False
    if "cl_platform_not_found_khr" in output:
        return False
    if "no opencl" in output:
        return False
    return True


def run(config: dict, data_dir: Path) -> None:
    requested_tool = config.get("tool", "aircrack-ng")
    tool = requested_tool
    wordlist = config["wordlist"]
    bssid = config.get("bssid", "")
    essid = (config.get("essid") or "").strip()
    timeout = config.get("timeout", 3600)

    log_path = data_dir / "log.txt"
    found_file = data_dir / "cracked.txt"
    if found_file.exists():
        found_file.unlink()

    def _write_result(
        *,
        tool_value: str,
        success: bool,
        password: str | None,
        stopped: bool,
        exit_code: int | None,
        failure_reason: str,
        capture_file: str | None,
        duration: float,
    ) -> None:
        result = {
            "bssid": bssid,
            "tool_requested": requested_tool,
            "tool": tool_value,
            "password": password,
            "success": success,
            "stopped_early": stopped,
            "exit_code": exit_code,
            "failure_reason": "" if success else failure_reason,
            "capture_file": capture_file,
            "duration_s": round(duration, 1),
        }
        (data_dir / "result.json").write_text(json.dumps(result, indent=2))

    if tool == "hashcat" and not _hashcat_runtime_available(log_path):
        log(log_path, "hashcat runtime is not available - using aircrack-ng")
        tool = "aircrack-ng"

    start = time.time()
    capture = _resolve_capture_file(config, data_dir, tool)
    if not capture and tool == "hashcat":
        log(log_path, "no hc22000 found - falling back to aircrack-ng")
        tool = "aircrack-ng"
        capture = _resolve_capture_file(config, data_dir, tool)

    if not capture:
        log(log_path, "ERROR: no valid capture file found")
        log(log_path, f"  config hc22000={config.get('hc22000')}")
        log(log_path, f"  config pcap={config.get('pcap')}")
        log(log_path, "SKIP: cracking is impossible until handshake/PMKID is captured")
        _write_result(
            tool_value=tool,
            success=False,
            password=None,
            stopped=False,
            exit_code=None,
            failure_reason="no_capture_material",
            capture_file=None,
            duration=time.time() - start,
        )
        return

    valid, validation_error = _validate_capture_for_tool(capture, tool)
    if not valid:
        log(log_path, f"ERROR: invalid input for {tool}: {validation_error}")
        _write_result(
            tool_value=tool,
            success=False,
            password=None,
            stopped=False,
            exit_code=None,
            failure_reason="invalid_capture_input",
            capture_file=capture,
            duration=time.time() - start,
        )
        return

    capture_size = Path(capture).stat().st_size
    wl_path = Path(wordlist)
    wl_size = wl_path.stat().st_size if wl_path.exists() else 0
    wl_lines = 0
    if wl_path.exists():
        try:
            r = subprocess.run(["wc", "-l", str(wl_path)], capture_output=True, text=True, timeout=10)
            wl_lines = int(r.stdout.strip().split()[0]) if r.returncode == 0 else 0
        except Exception:
            pass

    _update_status(data_dir, "running", f"cracking with {tool}")
    log(log_path, "=== PSK Crack ===")
    log(log_path, f"tool:      {tool} (requested: {requested_tool})")
    log(log_path, f"capture:   {capture} ({capture_size:,} bytes)")
    log(log_path, f"wordlist:  {wordlist} ({wl_size:,} bytes, ~{wl_lines:,} words)")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"essid:     {essid or '(not set)'}")
    log(log_path, f"timeout:   {timeout}s")

    password = None
    stopped = False
    exit_code = None
    failure_reason = ""
    aircrack_need_essid = False
    aircrack_cmac_missing = False

    if tool == "hashcat":
        password, stopped, exit_code = _run_hashcat(
            capture, wordlist, found_file, log_path, timeout, data_dir
        )
        if exit_code == 255 and not password and not stopped:
            log(log_path, "hashcat failed (no OpenCL runtime) - falling back to aircrack-ng")
            aircrack_capture = _resolve_capture_file(config, data_dir, "aircrack-ng") or capture
            valid, validation_error = _validate_capture_for_tool(aircrack_capture, "aircrack-ng")
            if not valid:
                raise RuntimeError(
                    f"Fallback to aircrack-ng failed due to invalid capture format: {validation_error}"
                )
            capture = aircrack_capture
            password, stopped, exit_code, aircrack_need_essid, aircrack_cmac_missing = _run_aircrack(
                aircrack_capture, bssid, essid, wordlist, found_file, log_path, timeout, data_dir
            )
            tool = "aircrack-ng"
            failure_reason = "hashcat_no_opencl"
    else:
        password, stopped, exit_code, aircrack_need_essid, aircrack_cmac_missing = _run_aircrack(
            capture, bssid, essid, wordlist, found_file, log_path, timeout, data_dir
        )

    if (
        tool == "aircrack-ng"
        and not password
        and not stopped
        and exit_code == 1
        and aircrack_need_essid
        and not essid
    ):
        detected_essid = _extract_essid_from_capture(capture, bssid, log_path)
        if detected_essid:
            log(log_path, "aircrack-ng requested ESSID - retrying with auto-detected ESSID")
            password, stopped, exit_code, aircrack_need_essid, aircrack_cmac_missing = _run_aircrack(
                capture,
                bssid,
                detected_essid,
                wordlist,
                found_file,
                log_path,
                timeout,
                data_dir,
            )
        else:
            log(log_path, "aircrack-ng requested ESSID but it was not found in capture")

    duration = round(time.time() - start, 1)
    if password:
        log(log_path, f"=== PASSWORD FOUND: {password} (in {duration}s) ===")
    elif stopped:
        log(log_path, f"=== Stopped by user after {duration}s ===")
        failure_reason = "stopped_by_user"
    else:
        log(log_path, f"=== Wordlist exhausted, password not found ({duration}s) ===")
        if tool == "aircrack-ng" and aircrack_cmac_missing:
            log(log_path, "aircrack-ng lacks CMAC support for this capture (OMAC1 warning)")
            failure_reason = failure_reason or "aircrack_cmac_unsupported"
        if tool == "aircrack-ng" and aircrack_need_essid:
            failure_reason = failure_reason or "aircrack_missing_essid"
        if exit_code and exit_code != 0:
            failure_reason = failure_reason or f"tool_exit_{exit_code}"
        else:
            failure_reason = "wordlist_exhausted"

    _write_result(
        tool_value=tool,
        success=password is not None,
        password=password,
        stopped=stopped,
        exit_code=exit_code,
        failure_reason=failure_reason,
        capture_file=capture,
        duration=duration,
    )


def _run_aircrack(
    capture: str,
    bssid: str,
    essid: str,
    wordlist: str,
    found_file: Path,
    log_path: Path,
    timeout: int,
    data_dir: Path,
) -> tuple[str | None, bool, int | None, bool, bool]:
    cmd = ["aircrack-ng", "-w", wordlist, "-l", str(found_file)]
    if bssid:
        cmd += ["-b", bssid]
    if essid:
        cmd += ["-e", essid]
    cmd.append(capture)

    log(log_path, f"exec: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    tl = ToolOutputLogger(log_path, prefix="aircrack> ")
    start = time.time()
    last_status = 0.0
    stopped = False
    need_essid = False
    cmac_missing = False

    try:
        while True:
            if proc.poll() is not None:
                drain_stdout_cr(proc, tl, AIRCRACK_IMPORTANT_RE)
                log(log_path, f"aircrack-ng exited (code={proc.returncode})")
                break
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested - terminating")
                proc.terminate()
                break
            if found_file.exists() and found_file.stat().st_size > 0:
                log(log_path, "cracked.txt appeared - password found!")
                proc.terminate()
                break
            elapsed = time.time() - start
            if elapsed > timeout:
                log(log_path, f"timeout reached ({timeout}s)")
                proc.terminate()
                break

            drain_stdout_cr(proc, tl, AIRCRACK_IMPORTANT_RE)
            if "ESSID is required" in (tl.last_status or ""):
                need_essid = True
            if "OMAC1 is only supported" in (tl.last_status or ""):
                cmac_missing = True

            if elapsed - last_status >= STATUS_INTERVAL:
                progress = f"aircrack-ng ({int(elapsed)}s)"
                if tl.last_status:
                    progress += f" | {tl.last_status[:120]}"
                _update_status(data_dir, "running", progress)
                log(log_path, f"  progress: {tl.last_status[:200] if tl.last_status else '(waiting for output)'}")
                last_status = elapsed
            time.sleep(0.3)
    finally:
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    if found_file.exists():
        pw = found_file.read_text(encoding="utf-8", errors="replace").strip() or None
        return pw, stopped, proc.returncode, need_essid, cmac_missing
    return None, stopped, proc.returncode, need_essid, cmac_missing


def _run_hashcat(
    hash_file: str, wordlist: str, found_file: Path, log_path: Path, timeout: int, data_dir: Path,
) -> tuple[str | None, bool, int | None]:
    cmd = [
        "hashcat", "-m", "22000", "-a", "0", "--force",
        "--status", "--status-timer", "10",
        "-o", str(found_file),
        hash_file, wordlist,
    ]

    log(log_path, f"exec: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tl = ToolOutputLogger(log_path, prefix="hashcat> ")
    start = time.time()
    last_status = 0.0
    stopped = False

    try:
        while True:
            if proc.poll() is not None:
                drain_stdout(proc, tl, HASHCAT_IMPORTANT_RE)
                log(log_path, f"hashcat exited (code={proc.returncode})")
                break
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested - terminating")
                proc.terminate()
                break
            if found_file.exists() and found_file.stat().st_size > 0:
                log(log_path, "output file appeared - password found!")
                proc.terminate()
                break
            elapsed = time.time() - start
            if elapsed > timeout:
                log(log_path, f"timeout reached ({timeout}s)")
                proc.terminate()
                break

            drain_stdout(proc, tl, HASHCAT_IMPORTANT_RE)

            if elapsed - last_status >= STATUS_INTERVAL:
                progress = f"hashcat ({int(elapsed)}s)"
                if tl.last_status:
                    progress += f" | {tl.last_status[:120]}"
                _update_status(data_dir, "running", progress)
                last_status = elapsed
            time.sleep(0.3)
    finally:
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    if found_file.exists():
        text = found_file.read_text(encoding="utf-8", errors="replace").strip()
        parts = text.split(":")
        return (parts[-1] if parts else None), stopped, proc.returncode
    return None, stopped, proc.returncode


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
