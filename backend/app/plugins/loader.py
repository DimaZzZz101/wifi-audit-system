"""Загрузка манифестов плагинов из каталога (JSON): один файл или папка на плагин."""
from pathlib import Path
import json
from typing import Any

from app.plugins.manifest import normalize_manifest


def load_plugins_from_dir(plugins_dir: str | None) -> list[dict[str, Any]]:
    """
    Load all plugin manifests from a directory.
    - If plugins_dir is None or empty or not a directory, return [].
    - Looks for: *.plugin.json in root, or subdirs with manifest.json / <name>.plugin.json.
    - Each valid JSON with required fields (id, name, type) is normalized and returned.
    """
    if not plugins_dir or not plugins_dir.strip():
        return []
    root = Path(plugins_dir).resolve()
    if not root.is_dir():
        return []

    loaded: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # Single file: *.plugin.json in root
    for path in root.glob("*.plugin.json"):
        try:
            data = _read_manifest(path)
            if data:
                norm = normalize_manifest(data)
                if norm["id"] not in seen_ids:
                    seen_ids.add(norm["id"])
                    loaded.append(norm)
        except (json.JSONDecodeError, ValueError):
            continue

    # Subdirs: <dir>/manifest.json or <dir>/<dir>.plugin.json
    for subdir in root.iterdir():
        if not subdir.is_dir():
            continue
        for name in ("manifest.json", f"{subdir.name}.plugin.json"):
            path = subdir / name
            if not path.is_file():
                continue
            try:
                data = _read_manifest(path)
                if data:
                    norm = normalize_manifest(data)
                    if norm["id"] not in seen_ids:
                        seen_ids.add(norm["id"])
                        loaded.append(norm)
            except (json.JSONDecodeError, ValueError):
                continue
            break

    return loaded


def _read_manifest(path: Path) -> dict[str, Any] | None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None
