"""Сбор информации о хосте: USB, PCI, сетевые интерфейсы, ФС. Выполняется в контейнере с доступом к /sys и /dev/bus/usb хоста."""
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_CMD_TIMEOUT = 10

# USB vendor IDs, часто используемые в Wi-Fi адаптерах (неполный список)
_USB_WIFI_VENDORS = frozenset({
    "0bda",   # Realtek
    "148f",   # Ralink / MediaTek
    "0cf3",   # Atheros / Qualcomm
    "2357",   # TP-Link
    "0e8d",   # MediaTek
    "2a70",   # ChipIdea (некоторые Wi-Fi)
    "04e8",   # Samsung (некоторые Wi-Fi)
    "0b05",   # ASUSTek (Wi-Fi адаптеры)
    "13b1",   # Linksys
    "050d",   # Belkin
    "07b8",   # D-Link
    "083a",   # Accton
    "157e",   # Intel (часть wireless)
})
_WIFI_NAME_SUBSTRINGS = ("wireless", "wlan", "wi-fi", "802.11", "wifi", "ralink", "realtek 802", "atheros", "intel wireless", "mediatek")
_FS_EXCLUDED_TYPES = frozenset({
    "tmpfs",
    "devtmpfs",
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "pstore",
    "debugfs",
    "tracefs",
    "securityfs",
    "configfs",
    "mqueue",
    "hugetlbfs",
    "fusectl",
    "autofs",
    "overlay",
    "nsfs",
    "squashfs",
    "ramfs",
})
_FS_EXCLUDED_MOUNT_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/lib/docker",
)
_FS_EXCLUDED_MOUNTS = frozenset({
    "/etc/hosts",
    "/etc/hostname",
    "/etc/resolv.conf",
})
_ARTIFACTS_MOUNT_POINT = (os.getenv("ARTIFACTS_DIR") or "/data/artifacts").strip() or "/data/artifacts"


def _run(cmd: list[str]) -> list[str] | None:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT,
        )
        if r.returncode != 0:
            return None
        return [s for s in (r.stdout or "").strip().splitlines() if s]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _is_usb_wifi(usb_id: str, name: str) -> bool:
    """Является ли USB-устройство Wi-Fi адаптером (по vendor и/или названию)."""
    name_lower = name.lower()
    if any(s in name_lower for s in _WIFI_NAME_SUBSTRINGS):
        return True
    try:
        vendor = usb_id.split(":")[0].lower()
        return vendor in _USB_WIFI_VENDORS
    except Exception:
        return False


def _is_pci_wifi(class_name: str, name: str) -> bool:
    """Является ли PCI-устройство Wi-Fi (Network controller + Wireless в названии)."""
    name_lower = name.lower()
    class_lower = (class_name or "").lower()
    if "network controller" not in class_lower and "network controller" not in name_lower:
        return False
    return any(s in name_lower for s in ("wireless", "wlan", "wi-fi", "802.11", "wifi"))


def get_usb_devices() -> list[dict[str, Any]]:
    """Список USB-устройств (lsusb). Требует доступ к /dev/bus/usb хоста. Добавляет wifi_capable."""
    out = _run(["lsusb"])
    if not out:
        return []
    devices: list[dict[str, Any]] = []
    pattern = re.compile(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.+)")
    for line in out:
        m = pattern.match(line)
        if m:
            dev_id = m.group(3)
            name = m.group(4).strip()
            devices.append({
                "bus": m.group(1),
                "device": m.group(2),
                "id": dev_id,
                "name": name,
                "wifi_capable": _is_usb_wifi(dev_id, name),
            })
    return devices


def get_pci_devices() -> list[dict[str, Any]]:
    """Список PCI-устройств (lspci). Требует доступ к /sys хоста. Добавляет wifi_capable."""
    out = _run(["lspci", "-mm"])
    if not out:
        out = _run(["lspci"])
    if not out:
        return []
    devices: list[dict[str, Any]] = []
    # lspci -mm: "00:00.0" "Class" "Vendor" "Device" ...
    mm_pattern = re.compile(r'^([0-9a-f.:]+)\s+"([^"]*)"\s+"([^"]*)"\s+"([^"]*)"')
    # Обычный lspci: "02:00.0 Network controller: Intel Corporation Wireless 8260 (rev 3a)"
    plain_pattern = re.compile(r"^([0-9a-f.:]+)\s+(.+?):\s+(.+)$")
    for line in out:
        m = mm_pattern.match(line)
        if m:
            slot, class_name, vendor, device_part = m.group(1), m.group(2), m.group(3), m.group(4)
            name = f"{vendor} {device_part}".strip() if vendor else (device_part or slot)
            devices.append({
                "slot": slot,
                "class_name": class_name,
                "name": name or slot,
                "wifi_capable": _is_pci_wifi(class_name, name),
            })
            continue
        m = plain_pattern.match(line)
        if m:
            slot, class_name, name = m.group(1), m.group(2).strip(), m.group(3).strip()
            devices.append({
                "slot": slot,
                "class_name": class_name,
                "name": name,
                "wifi_capable": _is_pci_wifi(class_name, name),
            })
    return devices


def get_network_interfaces() -> list[dict[str, Any]]:
    """Сетевые интерфейсы. В Docker /sys - с хоста, ip - из контейнера. Используем /sys/class/net как primary."""
    net = Path("/sys/class/net")
    if not net.exists():
        return []

    # Primary: /sys/class/net - при монтировании /sys с хоста даёт интерфейсы хоста (wlp3s0, wlx*, ...)
    # ip -o link в контейнере возвращает только eth0/lo, поэтому не используем его как источник имён
    result: list[dict[str, Any]] = []
    for p in net.iterdir():
        if p.is_dir() and not p.name.startswith("."):
            wireless = (p / "wireless").exists()
            result.append({
                "name": p.name,
                "flags": "",
                "wireless": wireless,
            })

    # Дополняем flags из ip (если интерфейс есть в текущем namespace)
    out = _run(["ip", "-o", "link", "show"])
    if out:
        pattern = re.compile(r"^\d+:\s+(\S+):\s+<([^>]*)>")
        name_to_flags: dict[str, str] = {}
        for line in out:
            m = pattern.match(line)
            if m:
                name_to_flags[m.group(1).rstrip(":")] = m.group(2)
        for r in result:
            r["flags"] = name_to_flags.get(r["name"], "")

    return sorted(result, key=lambda x: (not x["wireless"], x["name"]))


def get_filesystem_usage() -> list[dict[str, Any]]:
    """Использование файловых систем (df -T -h)."""
    out = _run(["df", "-T", "-h"])
    if not out:
        return []
    lines = out[1:] if len(out) > 1 else out
    result: list[dict[str, Any]] = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 6:
            fs_type = (parts[1] or "").lower()
            mount_point = " ".join(parts[6:]) if len(parts) > 6 else ""
            if not mount_point:
                continue
            # Системное хранилище артефактов показываем всегда.
            if mount_point == _ARTIFACTS_MOUNT_POINT:
                result.append({
                    "filesystem": parts[0],
                    "type": parts[1],
                    "size": parts[2],
                    "used": parts[3],
                    "available": parts[4],
                    "use_percent": parts[5],
                    "mounted_on": mount_point,
                })
                continue
            # Корень показываем всегда: это ключевой индикатор общего объёма носителя.
            if mount_point != "/" and fs_type in _FS_EXCLUDED_TYPES:
                continue
            if mount_point in _FS_EXCLUDED_MOUNTS:
                continue
            if any(mount_point == p or mount_point.startswith(f"{p}/") for p in _FS_EXCLUDED_MOUNT_PREFIXES):
                continue
            result.append({
                "filesystem": parts[0],
                "type": parts[1],
                "size": parts[2],
                "used": parts[3],
                "available": parts[4],
                "use_percent": parts[5],
                "mounted_on": mount_point,
            })
    return result


def get_hardware_summary(wifi_only: bool = False) -> dict[str, Any]:
    usb = get_usb_devices()
    pci = get_pci_devices()
    if wifi_only:
        usb = [d for d in usb if d.get("wifi_capable")]
        pci = [d for d in pci if d.get("wifi_capable")]
    return {
        "usb_devices": usb,
        "pci_devices": pci,
        "network_interfaces": get_network_interfaces(),
        "filesystem": get_filesystem_usage(),
    }
