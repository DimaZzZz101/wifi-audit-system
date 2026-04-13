"""PMKID capture using hcxdumptool filterlist targeting + hcxpcapngtool conversion."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from _log_util import log, ToolOutputLogger, drain_stdout

STATUS_INTERVAL = 10

IMPORTANT_RE = [
    re.compile(r"PMKID", re.I),
    re.compile(r"EAPOL", re.I),
    re.compile(r"FOUND", re.I),
    re.compile(r"handshake", re.I),
    re.compile(r"association", re.I),
]

_NOISE_RE = re.compile(
    r"TERM environment variable|"
    r"^CHA\|.*SCAN:|"
    r"^---\+--------\+",
    re.I,
)


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    interface = config["interface"]
    channel = config.get("channel")
    try:
        timeout = int(config.get("timeout", 120) or 120)
    except (TypeError, ValueError):
        timeout = 120

    log_path = data_dir / "log.txt"
    capture_file = data_dir / "capture.pcapng"
    filter_file = data_dir / "target.filter"
    hc22000 = data_dir / "pmkid.hc22000"
    target_bssid = bssid.strip().lower()

    log(log_path, "=== PMKID Capture ===")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"interface: {interface}")
    log(log_path, f"channel:   {channel or '(auto/hop)'}")
    log(log_path, f"timeout:   {timeout}s")

    _update_status(data_dir, "running", "preparing target filter")

    help_out = ""
    version_out = ""
    try:
        r_ver = subprocess.run(["hcxdumptool", "-v"], capture_output=True, text=True, timeout=10)
        version_out = ((r_ver.stdout or "") + " " + (r_ver.stderr or "")).strip()
    except Exception:
        pass
    try:
        # `-h` prints common options; `--help` prints extended docs.
        r_help_short = subprocess.run(["hcxdumptool", "-h"], capture_output=True, text=True, timeout=15)
        r_help_long = subprocess.run(["hcxdumptool", "--help"], capture_output=True, text=True, timeout=15)
        help_out = "\n".join(
            [
                r_help_short.stdout or "",
                r_help_short.stderr or "",
                r_help_long.stdout or "",
                r_help_long.stderr or "",
            ]
        )
    except Exception:
        pass

    filter_args: list[str] = []
    try:
        # PMKID must target only the AP selected in the audit plan.
        filter_file.write_text(f"{target_bssid}\n", encoding="utf-8")
        if "--filterlist_ap=" in help_out:
            filter_args = [f"--filterlist_ap={filter_file}", "--filtermode=2"]
        elif "--filterlist=" in help_out:
            filter_args = [f"--filterlist={filter_file}", "--filtermode=2"]
        else:
            raise RuntimeError(
                "hcxdumptool does not support --filterlist/--filterlist_ap "
                f"(version: {version_out or 'unknown'})"
            )
    except Exception as e:
        log(log_path, f"ERROR: failed to prepare target filterlist: {e}")
        raise RuntimeError(
            "PMKID requires hcxdumptool filterlist support; current image lacks it"
        ) from e

    log(log_path, f"target filter created ({filter_file.stat().st_size} bytes): {target_bssid}")

    _update_status(data_dir, "running", "capturing PMKID")

    output_opt = "-w" if "-w <outfile>" in help_out else "-o"
    disable_opt = (
        "--disable_disassociation"
        if "--disable_disassociation" in help_out
        else "--disable_deauthentication"
    )

    hcx_cmd = [
        "hcxdumptool",
        "-i", interface,
        output_opt, str(capture_file),
        disable_opt,
    ]
    if "--rds=" in help_out:
        hcx_cmd.append("--rds=1")
    hcx_cmd.extend(filter_args)
    if channel and "--channellist=" in help_out:
        try:
            hcx_cmd.append(f"--channellist={int(channel)}")
        except (TypeError, ValueError):
            log(log_path, f"warning: invalid channel value in config: {channel!r} (using channel hopping)")
    elif channel:
        try:
            hcx_cmd.extend(["-c", str(int(channel))])
        except (TypeError, ValueError):
            log(log_path, f"warning: invalid channel value in config: {channel!r} (using channel hopping)")

    log(log_path, f"exec: {' '.join(hcx_cmd)}")
    proc = subprocess.Popen(hcx_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tl = ToolOutputLogger(log_path, prefix="hcxdumptool> ", noise_filter=_NOISE_RE)
    start = time.time()
    stop_requested = False
    timed_out = False
    last_status = 0.0

    try:
        while True:
            if proc.poll() is not None:
                drain_stdout(proc, tl, IMPORTANT_RE)
                log(log_path, f"hcxdumptool exited (code={proc.returncode})")
                break
            if _is_stop_requested():
                stop_requested = True
                log(log_path, "stop requested")
                break

            drain_stdout(proc, tl, IMPORTANT_RE)

            elapsed = time.time() - start
            if elapsed >= timeout:
                timed_out = True
                log(log_path, f"timeout reached ({timeout}s)")
                break
            if elapsed - last_status >= STATUS_INTERVAL:
                cap_size = capture_file.stat().st_size if capture_file.exists() else 0
                progress = f"PMKID capturing ({int(elapsed)}s, {cap_size:,} B)"
                if tl.last_status and not _NOISE_RE.search(tl.last_status):
                    progress += f" | {tl.last_status[:80]}"
                _update_status(data_dir, "running", progress)
                last_status = elapsed
            time.sleep(0.3)

        if proc.poll() is None:
            if timed_out:
                log(log_path, "stopping hcxdumptool due to timeout")
            elif stop_requested:
                log(log_path, "stopping hcxdumptool due to stop request")
            # Graceful stop (similar to reference timeout --signal=INT).
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
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

    exit_code = proc.returncode
    run_time = time.time() - start

    if (
        not stop_requested
        and not capture_file.exists()
        and exit_code not in (0, None)
        and run_time < 10
    ):
        log(log_path, f"ERROR: hcxdumptool crashed early (code={exit_code})")
        raise RuntimeError(f"hcxdumptool exited early with code {exit_code}")

    log(log_path, "--- Post-processing ---")
    pmkid_count = 0
    pmkid_observed = 0
    pmkid_unsupported = 0
    if capture_file.exists() and capture_file.stat().st_size > 0:
        cap_size = capture_file.stat().st_size
        log(log_path, f"capture file: {cap_size:,} bytes")
        _update_status(data_dir, "running", "converting to hc22000")
        hcx_convert = ["hcxpcapngtool", "-o", str(hc22000), str(capture_file)]
        r = subprocess.run(hcx_convert, capture_output=True, text=True, timeout=60)
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                log(log_path, f"  hcxpcapngtool> {line.strip()[:200]}")
                m_total = re.search(r"RSN PMKID \(total\).*:\s*(\d+)", line)
                if m_total:
                    pmkid_observed = max(pmkid_observed, int(m_total.group(1)))
                m_unsupported = re.search(
                    r"RSN PMKID .*:\s*(\d+)\s+\(not supported by hashcat/JtR\)",
                    line,
                    flags=re.I,
                )
                if m_unsupported:
                    pmkid_unsupported += int(m_unsupported.group(1))
        if hc22000.exists():
            pmkid_count = sum(1 for line in hc22000.read_text().splitlines() if line.strip())
            log(log_path, f"hc22000: {pmkid_count} PMKID hash(es) extracted")
        else:
            log(log_path, "hcxpcapngtool: no PMKID material found")
        if pmkid_count == 0 and pmkid_observed > 0:
            log(
                log_path,
                "PMKID detected in traffic but unsupported for hc22000/hashcat "
                f"(observed={pmkid_observed}, unsupported={pmkid_unsupported})",
            )
    else:
        log(log_path, "no capture data - nothing to convert")

    if pmkid_count > 0:
        status = f"PMKID FOUND ({pmkid_count})"
    elif pmkid_observed > 0:
        status = f"PMKID unsupported ({pmkid_observed})"
    else:
        status = "no PMKID"
    duration = round(time.time() - start, 1)
    log(log_path, f"=== Result: {status} | {duration}s ===")

    result = {
        "bssid": bssid,
        "pmkid_found": pmkid_count > 0,
        "pmkid_count": pmkid_count,
        "pmkid_observed_count": pmkid_observed,
        "pmkid_unsupported_count": pmkid_unsupported,
        "exit_code": exit_code,
        "capture_file": str(capture_file) if capture_file.exists() else None,
        "hc22000": str(hc22000) if hc22000.exists() else None,
        "duration_s": duration,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
