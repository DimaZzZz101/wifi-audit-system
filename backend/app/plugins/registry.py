"""Реестр плагинов: встроенные плагины и загрузка из каталога."""
from typing import Any

from app.plugins.manifest import normalize_manifest
from app.plugins.loader import load_plugins_from_dir

# Capability: provides tiles for the Status page
STATUS_TILES = "status_tiles"

# Capability: can be run as a container (instrumental/service)
CONTAINER_RUNNABLE = "container_runnable"

# Built-in system plugins (id -> descriptor). Same shape as manifest.
SYSTEM_PLUGINS: dict[str, dict[str, Any]] = {
    "system_metrics": {
        "id": "system_metrics",
        "name": "System Metrics",
        "type": "system",
        "version": "1.0.0",
        "description": "Host (RAM, CPU, DISK) + system containers (db, api, frontend, tool-manager). Renders Status page tiles.",
        "provides": [STATUS_TILES],
        "container": None,
        "frontend": None,
    },
    "hardware": {
        "id": "hardware",
        "name": "Hardware",
        "type": "system",
        "version": "1.0.0",
        "description": "Сбор информации о хосте: USB-устройства, сетевые интерфейсы (Wi-Fi), файловые системы. Полезно для аудита Wi-Fi.",
        "provides": [],
        "container": None,
        "frontend": None,
    },
}


def _all_plugins(plugins_dir: str | None) -> list[dict[str, Any]]:
    """Merge system plugins with directory-loaded; dedupe by id (system wins)."""
    by_id: dict[str, dict[str, Any]] = {}
    for p in load_plugins_from_dir(plugins_dir):
        by_id[p["id"]] = p
    for pid, p in SYSTEM_PLUGINS.items():
        normalized = normalize_manifest(
            {
                "id": p["id"],
                "name": p["name"],
                "type": p["type"],
                "description": p.get("description"),
                "version": p.get("version"),
                "author": p.get("author"),
                "provides": p.get("provides") or [],
                "container": p.get("container"),
                "frontend": p.get("frontend"),
            }
        )
        by_id[pid] = normalized
    return list(by_id.values())


def list_plugins(
    provides: str | None = None,
    plugins_dir: str | None = None,
) -> list[dict[str, Any]]:
    """List plugins, optionally filtered by capability (e.g. status_tiles)."""
    result = _all_plugins(plugins_dir)
    if provides:
        result = [p for p in result if provides in (p.get("provides") or [])]
    return result


def get_plugin(plugin_id: str, plugins_dir: str | None = None) -> dict[str, Any] | None:
    """Get one plugin by id. Returns None if not found."""
    for p in _all_plugins(plugins_dir):
        if p.get("id") == plugin_id:
            return p
    return None
