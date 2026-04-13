#!/usr/bin/env python3
"""
Оркестратор сканирования Wi-Fi сетей.

Запускает airodump-ng, периодически вызывает парсер (CSV + tshark pcap + wash -> recon.json),
управляет жизненным циклом (continuous/timed), обрабатывает SIGTERM для graceful shutdown.

ENV:
  INTERFACE     - имя интерфейса в monitor mode (обязательно)
  SCAN_MODE     - continuous | timed (по умолчанию continuous)
  SCAN_DURATION - секунды (только для timed)
  SCAN_ID       - UUID скана (обязательно)
  SESSION_DIR   - /data/session (mount point)
  BANDS         - bg | a | abg (по умолчанию abg)
  CHANNELS      - опционально: список каналов через запятую
"""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PARSE_INTERVAL = 3
STATUS_FILE = "status.json"

ALL_CHANNELS_24 = set(range(1, 15))
ALL_CHANNELS_5 = {
    36, 40, 44, 48,
    52, 56, 60, 64,
    100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144,
    149, 153, 157, 161, 165, 169, 173, 177,
}
ALL_CHANNELS = ALL_CHANNELS_24 | ALL_CHANNELS_5


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fail(msg: str) -> None:
    print(json.dumps({"success": False, "error": msg}), file=sys.stderr)
    sys.exit(1)


def set_permissive_regdomain() -> None:
    """Set regulatory domain to 'US' for maximum channel availability.

    US covers 2.4 GHz ch 1-11, 5 GHz UNII-1/2/2e/3 (ch 36-165).
    The world domain '00' disables many 5 GHz channels on some drivers,
    so US is a better choice for pentesting tools.
    """
    try:
        cur = subprocess.run(
            ["iw", "reg", "get"], capture_output=True, text=True, timeout=5,
        )
        current_reg = ""
        for line in (cur.stdout or "").splitlines():
            if "country" in line:
                current_reg = line.strip()
                break
        print(f"[scanner] current regulatory domain: {current_reg}", file=sys.stderr)

        subprocess.run(
            ["iw", "reg", "set", "US"], capture_output=True, timeout=5,
        )

        after = subprocess.run(
            ["iw", "reg", "get"], capture_output=True, text=True, timeout=5,
        )
        for line in (after.stdout or "").splitlines():
            if "country" in line:
                print(f"[scanner] regulatory domain set to: {line.strip()}", file=sys.stderr)
                break
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"[scanner] warning: could not set regulatory domain: {e}", file=sys.stderr)


def check_monitor_mode(interface: str) -> None:
    """Verify the interface is in monitor mode via iw."""
    try:
        r = subprocess.run(
            ["iw", "dev", interface, "info"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            fail(f"Interface {interface} not found: {r.stderr.strip()}")
        if "type monitor" not in r.stdout:
            fail(
                f"Interface {interface} is not in monitor mode. "
                "Set monitor mode first via Settings > Wi-Fi."
            )
    except FileNotFoundError:
        fail("iw not found in container")


def build_airodump_cmd(
    interface: str,
    output_prefix: str,
    bands: str,
    channels: str | None,
) -> list[str]:
    cmd = [
        "airodump-ng",
        interface,
        "-w", output_prefix,
        "--output-format", "csv,pcap",
        "--write-interval", "1",
    ]
    if channels:
        cmd.extend(["-c", channels])
    elif bands:
        cmd.extend(["--band", bands])
    return cmd


def all_channel_list(bands: str) -> str:
    """Build a comma-separated list of ALL known channels for the given bands."""
    chs: set[int] = set()
    if "b" in bands or "g" in bands:
        chs |= ALL_CHANNELS_24
    if "a" in bands:
        chs |= ALL_CHANNELS_5
    return ",".join(str(c) for c in sorted(chs))


def write_status(scan_dir: Path, **fields) -> None:
    path = scan_dir / STATUS_FILE
    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    existing.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    tmp.rename(path)


def run_parser(scan_dir: Path, csv_path: Path, pcap_path: Path, scan_meta: dict) -> None:
    """Call recon_parser to generate recon.json from CSV + pcap."""
    cmd = [
        "python3", "/app/recon_parser.py",
        "--scan-dir", str(scan_dir),
        "--csv", str(csv_path),
        "--pcap", str(pcap_path),
        "--scan-id", scan_meta["scan_id"],
        "--started-at", scan_meta["started_at"],
        "--scan-mode", scan_meta["scan_mode"],
        "--interface", scan_meta["interface"],
        "--bands", scan_meta["bands"],
    ]
    mac_filter_type = scan_meta.get("mac_filter_type")
    mac_filter_file = scan_meta.get("mac_filter_file")
    if mac_filter_type and mac_filter_file and Path(mac_filter_file).exists():
        cmd.extend(["--mac-filter", mac_filter_file, "--mac-filter-type", mac_filter_type])
    try:
        subprocess.run(cmd, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"[scanner] parser error: {e}", file=sys.stderr)


def find_airodump_files(scan_dir: Path, prefix: str) -> tuple[Path | None, Path | None]:
    """Find the latest airodump CSV and pcap files (airodump appends -01, -02, etc.)."""
    csvs = sorted(scan_dir.glob(f"{prefix}-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    caps = sorted(
        list(scan_dir.glob(f"{prefix}-*.cap")) + list(scan_dir.glob(f"{prefix}-*.pcap")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return (csvs[0] if csvs else None, caps[0] if caps else None)


class GracefulShutdown:
    def __init__(self):
        self.should_stop = False
        signal.signal(signal.SIGTERM, self._handler)
        signal.signal(signal.SIGINT, self._handler)

    def _handler(self, signum, frame):
        print(f"[scanner] received signal {signum}, shutting down...", file=sys.stderr)
        self.should_stop = True


def main() -> None:
    interface = os.environ.get("INTERFACE", "").strip()
    scan_mode = os.environ.get("SCAN_MODE", "continuous").strip().lower()
    scan_duration_str = os.environ.get("SCAN_DURATION", "").strip()
    scan_id = os.environ.get("SCAN_ID", "").strip()
    scan_folder = os.environ.get("SCAN_FOLDER", "").strip() or scan_id
    session_dir = Path(os.environ.get("SESSION_DIR", "/data/session").strip())
    bands = os.environ.get("BANDS", "abg").strip().lower()
    channels_env = os.environ.get("CHANNELS", "").strip()

    if not interface:
        fail("INTERFACE not set")
    if not scan_id:
        fail("SCAN_ID not set")
    if scan_mode not in ("continuous", "timed"):
        fail(f"Invalid SCAN_MODE: {scan_mode}")

    scan_duration: int | None = None
    if scan_mode == "timed":
        try:
            scan_duration = int(scan_duration_str)
            if scan_duration < 5:
                fail("SCAN_DURATION must be >= 5 seconds")
        except ValueError:
            fail(f"Invalid SCAN_DURATION: {scan_duration_str}")

    set_permissive_regdomain()
    check_monitor_mode(interface)

    scan_dir = session_dir / "scans" / scan_folder
    scan_dir.mkdir(parents=True, exist_ok=True)

    channels = channels_env or None

    mac_filter_type = os.environ.get("MAC_FILTER_TYPE", "").strip() or None
    mac_filter_file = str(session_dir / "mac_filter.txt")

    output_prefix = str(scan_dir / "dump")
    cmd = build_airodump_cmd(interface, output_prefix, bands, channels)

    started_at = utcnow()
    scan_meta = {
        "scan_id": scan_id,
        "started_at": started_at,
        "scan_mode": scan_mode,
        "interface": interface,
        "bands": bands,
        "mac_filter_type": mac_filter_type,
        "mac_filter_file": mac_filter_file,
    }

    write_status(scan_dir, is_running=True, started_at=started_at, stopped_at=None, error=None)

    print(f"[scanner] starting airodump-ng: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    shutdown = GracefulShutdown()
    start_time = time.monotonic()
    last_parse = 0.0

    try:
        while not shutdown.should_stop:
            elapsed = time.monotonic() - start_time

            if scan_mode == "timed" and scan_duration and elapsed >= scan_duration:
                print(f"[scanner] timed scan complete ({scan_duration}s)", file=sys.stderr)
                break

            if proc.poll() is not None:
                print(f"[scanner] airodump-ng exited with code {proc.returncode}", file=sys.stderr)
                break

            if time.monotonic() - last_parse >= PARSE_INTERVAL:
                csv_file, pcap_file = find_airodump_files(scan_dir, "dump")
                if csv_file:
                    run_parser(scan_dir, csv_file, pcap_file or Path("/dev/null"), scan_meta)
                last_parse = time.monotonic()

            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            print("[scanner] terminating airodump-ng...", file=sys.stderr)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

        csv_file, pcap_file = find_airodump_files(scan_dir, "dump")
        if csv_file:
            print("[scanner] final parse...", file=sys.stderr)
            run_parser(scan_dir, csv_file, pcap_file or Path("/dev/null"), scan_meta)

        stopped_at = utcnow()
        write_status(scan_dir, is_running=False, stopped_at=stopped_at)

        recon_path = scan_dir / "recon.json"
        if recon_path.exists():
            try:
                data = json.loads(recon_path.read_text())
                data["stopped_at"] = stopped_at
                data["is_running"] = False
                tmp = recon_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                tmp.rename(recon_path)
            except (json.JSONDecodeError, OSError):
                pass

        print(f"[scanner] done. Artifacts in {scan_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
