#!/usr/bin/env python3
"""
Настройка Wi-Fi адаптера: режим (monitor/managed), канал, TX power, MAC.
Идемпотентно: если состояние уже совпадает - ничего не делает.
Использует iw + ip. Запускается с network_mode: host, cap_add: [NET_ADMIN].

Режим monitor: создаётся новый интерфейс с суффиксом mon (wlan0 -> wlan0mon).
Режим managed: создаётся интерфейс без суффикса (wlan0mon -> wlan0).

Переименование интерфейсов - отдельно на хосте через systemd .link (см. scripts/wifi-rename-link.sh).

Env:
  INTERFACE  - имя интерфейса (обязательно)
  MODE       - info | monitor | managed
  CHANNEL    - номер канала (1-165+, опционально)
  TXPOWER    - мощность в dBm (целое, опционально)
  MAC        - MAC-адрес XX:XX:XX:XX:XX:XX (опционально)
"""
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def run(cmd: list[str], timeout: int = 10) -> tuple[str, int]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return out, r.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return str(e), -1


def fail(error: str, **extra: Any) -> None:
    print(json.dumps({"success": False, "error": error, **extra}, ensure_ascii=False))
    sys.exit(1)


def ok(data: dict[str, Any]) -> None:
    print(json.dumps({"success": True, **data}, ensure_ascii=False))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Парсинг iw
# ---------------------------------------------------------------------------

def get_interface_info(interface: str) -> dict[str, Any] | None:
    """iw dev <iface> info -> mode, channel, freq (MHz), txpower (dBm), mac, phy."""
    out, code = run(["iw", "dev", interface, "info"])
    if code != 0:
        return None
    info: dict[str, Any] = {
        "mode": "",
        "channel": None,
        "freq": None,
        "txpower": None,
        "mac": None,
        "phy": None,
    }
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("type "):
            info["mode"] = line.split(None, 1)[1]
        elif line.startswith("channel "):
            m = re.match(r"channel\s+(\d+)\s+\((\d+)\s+MHz\)", line)
            if m:
                info["channel"] = int(m.group(1))
                info["freq"] = int(m.group(2))
        elif line.startswith("txpower "):
            m = re.search(r"([\d.]+)\s+dBm", line)
            if m:
                info["txpower"] = float(m.group(1))
        elif line.startswith("addr "):
            info["mac"] = line.split(None, 1)[1].strip()
        elif line.startswith("wiphy "):
            m = re.search(r"(\d+)", line)
            if m:
                info["phy"] = f"phy{m.group(1)}"
    return info


def get_phy_capabilities(phy: str) -> list[dict[str, Any]]:
    """iw phy <phy> info -> supported channels with freq, max_power, dfs, disabled."""
    out, code = run(["iw", "phy", phy, "info"], timeout=15)
    if code != 0:
        return []
    channels: list[dict[str, Any]] = []
    band = ""
    in_freqs = False
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("Band "):
            m = re.match(r"Band\s+(\d+):", stripped)
            if m:
                band_num = int(m.group(1))
                band = "2.4" if band_num == 1 else "5" if band_num == 2 else str(band_num)
            in_freqs = False
            continue
        if stripped == "Frequencies:":
            in_freqs = True
            continue
        if in_freqs:
            if not stripped.startswith("*"):
                in_freqs = False
                continue
            m = re.match(
                r"\*\s+(\d+)\s+MHz\s+\[(\d+)\](?:\s+\(([\d.]+)\s+dBm\))?",
                stripped,
            )
            if m:
                freq = int(m.group(1))
                ch = int(m.group(2))
                max_power = float(m.group(3)) if m.group(3) else None
                disabled = "(disabled)" in stripped
                dfs = "radar detection" in stripped.lower()
                channels.append({
                    "channel": ch,
                    "freq": freq,
                    "band": band,
                    "max_power_dbm": max_power,
                    "dfs": dfs,
                    "disabled": disabled,
                })
    return channels


def get_reg_domain() -> str:
    out, code = run(["iw", "reg", "get"])
    if code != 0:
        return ""
    for line in out.splitlines():
        m = re.search(r"country\s+([A-Z]{2})", line)
        if m:
            return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Действия
# ---------------------------------------------------------------------------

def iface_down(interface: str) -> None:
    out, code = run(["ip", "link", "set", "dev", interface, "down"])
    if code != 0:
        fail(f"Failed to bring {interface} down: {out}")


def iface_up(interface: str) -> None:
    out, code = run(["ip", "link", "set", "dev", interface, "up"])
    if code != 0:
        fail(f"Failed to bring {interface} up: {out}")


def iface_del(interface: str) -> None:
    """Удалить интерфейс (iw dev X del)."""
    out, code = run(["iw", "dev", interface, "del"])
    if code != 0:
        fail(f"iw dev {interface} del failed: {out}")


def iface_add(phy: str, name: str, iface_type: str) -> None:
    """Создать интерфейс на phy (iw phy X interface add NAME type TYPE)."""
    out, code = run(["iw", "phy", phy, "interface", "add", name, "type", iface_type])
    if code != 0:
        fail(f"iw phy {phy} interface add {name} type {iface_type} failed: {out}")


def _get_base_name(iface: str) -> str:
    """wlan0mon -> wlan0, wlan0 -> wlan0."""
    if iface.endswith("mon"):
        return iface[:-3]
    return iface


def _get_mon_name(base: str) -> str:
    """wlan0 -> wlan0mon."""
    return base + "mon"


def set_channel(interface: str, channel: int) -> None:
    out, code = run(["iw", "dev", interface, "set", "channel", str(channel)])
    if code != 0:
        fail(f"iw set channel {channel} failed: {out}")


def set_txpower(interface: str, dbm: int) -> bool:
    """Установить TX power (mBm = dBm * 100). Возвращает True при успехе, False если драйвер не поддерживает."""
    mbm = dbm * 100
    for mode in ("fixed", "limit"):
        _, code = run(["iw", "dev", interface, "set", "txpower", mode, str(mbm)])
        if code == 0:
            return True
    return False


def set_mac(interface: str, mac: str) -> None:
    out, code = run(["ip", "link", "set", "dev", interface, "address", mac])
    if code != 0:
        fail(f"ip link set address {mac} failed: {out}")


# ---------------------------------------------------------------------------
# Главная логика
# ---------------------------------------------------------------------------

def main() -> None:
    interface = os.environ.get("INTERFACE", "").strip()
    mode = os.environ.get("MODE", "").strip().lower()
    channel_str = os.environ.get("CHANNEL", "").strip()
    txpower_str = os.environ.get("TXPOWER", "").strip()
    mac_str = os.environ.get("MAC", "").strip()

    if not interface:
        fail("INTERFACE not set")

    # --- MODE=info: расширенная информация ---
    if mode == "info":
        current = get_interface_info(interface)
        if current is None:
            out, _ = run(["iw", "dev", interface, "info"])
            fail(f"Interface {interface} not found", stderr=out)

        # Set permissive regdomain so `iw phy info` reports all HW-supported
        # channels as enabled (not "(disabled)").
        run(["iw", "reg", "set", "US"], timeout=5)

        phy = current.get("phy") or ""
        raw_channels = get_phy_capabilities(phy) if phy else []
        reg = get_reg_domain()
        supported = [c for c in raw_channels if not c.get("disabled")]

        ok({
            "mode": current["mode"],
            "channel": current["channel"],
            "freq": current["freq"],
            "txpower": current["txpower"],
            "mac": current["mac"],
            "phy": phy,
            "reg_domain": reg,
            "supported_channels": supported,
        })

    # --- Валидация параметров ---
    if mode not in ("monitor", "managed"):
        fail(f"Invalid MODE: {mode}. Use info, monitor, or managed.")

    channel: int | None = None
    if channel_str and mode == "monitor":
        try:
            channel = int(channel_str)
            if channel < 1 or channel > 196:
                fail(f"Invalid channel: {channel}")
        except ValueError:
            fail(f"Invalid CHANNEL: {channel_str}")

    txpower: int | None = None
    if txpower_str:
        try:
            txpower = int(txpower_str)
            if txpower < 0:
                fail(f"TX power must be >= 0 dBm, got {txpower}")
        except ValueError:
            fail(f"Invalid TXPOWER: {txpower_str}")

    mac: str | None = None
    if mac_str:
        if not MAC_RE.match(mac_str):
            fail(f"Invalid MAC format: {mac_str}. Expected XX:XX:XX:XX:XX:XX")
        mac = mac_str

    # Set permissive regdomain so all HW-supported channels are available
    run(["iw", "reg", "set", "US"], timeout=5)

    # --- Текущее состояние ---
    current = get_interface_info(interface)
    if current is None:
        out, _ = run(["iw", "dev", interface, "info"])
        fail(f"Interface {interface} not found or not wireless", stderr=out)

    # --- Идемпотентность ---
    mode_ok = current["mode"] == mode
    channel_ok = channel is None or current.get("channel") == channel
    txpower_ok = txpower is None or (
        current.get("txpower") is not None and abs(current["txpower"] - txpower) < 0.5
    )
    mac_ok = mac is None or (
        current.get("mac") and current["mac"].lower() == mac.lower()
    )

    if mode_ok and channel_ok and txpower_ok and mac_ok:
        ok({
            "idempotent": True,
            "message": "Already in desired state",
            "actual_mode": current["mode"],
            "actual_interface": interface,
            "actual_channel": current.get("channel"),
            "actual_txpower": current.get("txpower"),
            "actual_mac": current.get("mac"),
        })

    # --- Применение: при смене режима - удалить интерфейс и создать новый с суффиксом mon ---
    working_iface = interface
    phy = current.get("phy") or ""
    if not phy:
        fail("Could not determine phy for interface")

    if not mode_ok:
        base = _get_base_name(interface)
        iface_down(interface)
        iface_del(interface)
        if mode == "monitor":
            working_iface = _get_mon_name(base)
            iface_add(phy, working_iface, "monitor")
        else:
            working_iface = base
            iface_add(phy, working_iface, "managed")
        iface_up(working_iface)

    if channel is not None and not channel_ok:
        set_channel(working_iface, channel)

    txpower_warning: str | None = None
    if txpower is not None and not txpower_ok:
        if not set_txpower(working_iface, txpower):
            txpower_warning = (
                f"TX power {txpower} dBm не установлен: драйвер не поддерживает. "
                "Режим и канал применены."
            )

    if mac is not None and not mac_ok:
        iface_down(working_iface)
        set_mac(working_iface, mac)
        iface_up(working_iface)

    # --- Верификация (retry: интерфейс может быть не готов сразу после создания) ---
    verified = None
    for attempt in range(5):
        if attempt > 0:
            time.sleep(0.5 + 0.5 * attempt)
        verified = get_interface_info(working_iface)
        if verified is not None:
            break
    if verified is None:
        iw_out, _ = run(["iw", "dev", working_iface, "info"])
        fail(
            f"Verification failed: could not read interface {working_iface} after apply. "
            f"iw dev {working_iface} info: {iw_out.strip() or 'exit non-zero'}"
        )

    if verified["mode"] != mode:
        fail(f"Verification: mode is {verified['mode']}, expected {mode}")

    # Канал проверяем только в monitor; в managed канал не фиксирован
    if mode == "monitor" and channel is not None and verified.get("channel") != channel:
        fail(f"Verification: channel is {verified.get('channel')}, expected {channel}")

    result: dict[str, Any] = {
        "idempotent": False,
        "message": "Applied and verified",
        "actual_mode": verified["mode"],
        "actual_interface": working_iface,
        "actual_channel": verified.get("channel"),
        "actual_txpower": verified.get("txpower"),
        "actual_mac": verified.get("mac"),
    }
    if txpower_warning:
        result["txpower_warning"] = txpower_warning
    ok(result)


if __name__ == "__main__":
    main()
