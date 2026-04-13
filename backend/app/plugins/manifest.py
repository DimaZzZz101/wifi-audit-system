"""Схема манифеста плагина. Соответствует JSON на диске и SYSTEM_PLUGINS."""
from typing import Any

# Required in manifest: id, name, type
# Optional: version, description, author, provides[], container{}, frontend{}
MANIFEST_REQUIRED = frozenset({"id", "name", "type"})


def normalize_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a plugin manifest. Raises ValueError if invalid."""
    missing = MANIFEST_REQUIRED - set(raw.keys())
    if missing:
        raise ValueError(f"Manifest missing required fields: {missing}")
    id_ = str(raw["id"]).strip()
    name = str(raw["name"]).strip()
    type_ = str(raw["type"]).strip()
    if not id_:
        raise ValueError("Plugin id cannot be empty")
    if not name:
        raise ValueError("Plugin name cannot be empty")

    out: dict[str, Any] = {
        "id": id_,
        "name": name,
        "type": type_,
        "description": raw.get("description"),
        "version": raw.get("version"),
        "author": raw.get("author"),
        "provides": list(raw["provides"]) if isinstance(raw.get("provides"), list) else [],
    }
    if out["description"] is not None:
        out["description"] = str(out["description"])
    if out["version"] is not None:
        out["version"] = str(out["version"])
    if out["author"] is not None:
        out["author"] = str(out["author"])

    # container: optional { image, type?, default_command? }
    container = raw.get("container")
    if container is not None and isinstance(container, dict):
        img = container.get("image")
        out["container"] = {
            "image": str(img).strip() if img else None,
            "type": str(container.get("type", "instrumental")).strip() or "instrumental",
            "default_command": container.get("default_command"),  # str or list
        }
        if out["container"]["default_command"] is not None and isinstance(
            out["container"]["default_command"], list
        ):
            pass  # keep as list
        elif out["container"]["default_command"] is not None:
            out["container"]["default_command"] = str(out["container"]["default_command"])
    else:
        out["container"] = None

    # frontend: optional { bundle_url? } for future UMD loading
    frontend = raw.get("frontend")
    if frontend is not None and isinstance(frontend, dict):
        out["frontend"] = {
            "bundle_url": str(frontend["bundle_url"]).strip() if frontend.get("bundle_url") else None,
        }
    else:
        out["frontend"] = None

    return out
