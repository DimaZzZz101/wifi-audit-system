#!/usr/bin/env python3
"""
Сбор информации о Wi-Fi интерфейсах (iw dev).
Вывод в JSON для отображения в web. Запускается в короткоживущем контейнере с network_mode: host.
"""
import json
import subprocess
import sys
from typing import Any


def run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return str(e)


def get_interfaces() -> list[dict[str, Any]]:
    """Список беспроводных интерфейсов (iw dev)."""
    out = run(["iw", "dev"])
    interfaces: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Interface "):
            if current:
                interfaces.append(current)
            current = {"name": line.split()[1], "phy": "", "type": ""}
        elif line.startswith("phy #"):
            current["phy"] = line
        elif line.startswith("type "):
            current["type"] = line.replace("type ", "")
        elif "channel" in line or "freq" in line:
            current["channel_info"] = line
    if current:
        interfaces.append(current)
    return interfaces


def main() -> None:
    result: dict[str, Any] = {
        "interfaces": get_interfaces(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
