"""Сервис инструментов проекта - запуск tool-контейнеров в контексте проекта аудита."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services import tool_manager_client
from app.services.session_service import get_project_dir

AVAILABLE_TOOLS: dict[str, dict[str, Any]] = {
    "wifi_info": {
        "id": "wifi_info",
        "name": "Wi-Fi Info",
        "description": "Информация о беспроводных интерфейсах (iw dev). Выводит список Wi-Fi адаптеров и их параметры.",
        "image": "wizzard_tools-wifi-info:latest",
        "network_mode": "host",
        "timeout": 30,
        "cap_add": None,
    },
    "wifi_setup": {
        "id": "wifi_setup",
        "name": "Wi-Fi Setup",
        "description": "Настройка Wi-Fi адаптера: режим, канал, TX power, MAC. Идемпотентно.",
        "image": "wizzard_tools-wifi-setup:latest",
        "network_mode": "host",
        "timeout": 30,
        "cap_add": ["NET_ADMIN", "SYS_MODULE"],
    },
    "recon": {
        "id": "recon",
        "name": "Recon Scanner",
        "description": "Сканирование Wi-Fi сетей: AP, STA, IE, WPS. airodump-ng + tshark.",
        "image": "wizzard_tools-recon:latest",
        "network_mode": "host",
        "timeout": None,
        "cap_add": ["NET_ADMIN", "NET_RAW", "SYS_MODULE"],
    },
}


def get_tool_definition(tool_id: str) -> dict[str, Any] | None:
    """Возвращает определение инструмента по id или None."""
    return AVAILABLE_TOOLS.get(tool_id)


def list_available_tools() -> list[dict[str, Any]]:
    return [
        {"id": t["id"], "name": t["name"], "description": t["description"], "image": t["image"]}
        for t in AVAILABLE_TOOLS.values()
    ]


def _project_artifacts_host_path(slug: str) -> str:
    """Host path to project artifacts (for Docker volume mount)."""
    return str(get_project_dir(slug))


def _make_container_name(slug: str, tool_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"wifiaudit-{slug}-{tool_id}-{ts}"


async def run_session_tool(
    token: str,
    slug: str,
    tool_id: str,
) -> dict[str, Any]:
    """Run a tool container scoped to a project. Save results and logs."""
    tool = AVAILABLE_TOOLS.get(tool_id)
    if not tool:
        raise ValueError(f"Unknown tool: {tool_id}")

    project_dir = get_project_dir(slug)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {slug}")

    container_name = _make_container_name(slug, tool_id)

    project_host_path = _project_artifacts_host_path(slug)
    volumes = [f"{project_host_path}:/data/session:rw"]

    labels = {
        "wifiaudit.project": slug,
        "wifiaudit.tool-name": tool_id,
    }

    result = await tool_manager_client.tool_manager_run_tool(
        token=token,
        image=tool["image"],
        command=None,
        env={"SESSION_SLUG": slug, "SESSION_DIR": "/data/session"},
        network_mode=tool["network_mode"],
        cap_add=tool.get("cap_add"),
        volumes=volumes,
        timeout=tool["timeout"],
        container_name=container_name,
        labels=labels,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _save_tool_output(project_dir, tool_id, ts, result)

    return {
        "tool_id": tool_id,
        "tool_name": tool["name"],
        "container_name": container_name,
        "exit_code": result.get("exit_code", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "saved_to": f"results/{tool_id}_{ts}.json",
    }


def _save_tool_output(project_dir: Path, tool_id: str, ts: str, result: dict[str, Any]) -> None:
    """Save tool stdout to results/ as JSON and raw log to logs/."""
    results_dir = project_dir / "results"
    logs_dir = project_dir / "logs"
    results_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    stdout = result.get("stdout", "")
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = {"raw_output": stdout}

    result_data = {
        "tool_id": tool_id,
        "timestamp": ts,
        "exit_code": result.get("exit_code", -1),
        "data": parsed,
    }
    result_path = results_dir / f"{tool_id}_{ts}.json"
    result_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

    log_content = f"=== {tool_id} @ {ts} ===\n"
    log_content += f"exit_code: {result.get('exit_code', -1)}\n\n"
    if stdout:
        log_content += f"--- stdout ---\n{stdout}\n"
    stderr = result.get("stderr", "")
    if stderr:
        log_content += f"\n--- stderr ---\n{stderr}\n"

    log_path = logs_dir / f"{tool_id}_{ts}.log"
    log_path.write_text(log_content, encoding="utf-8")


def list_tool_runs(slug: str) -> list[dict[str, Any]]:
    """List past tool runs from results/ directory."""
    project_dir = get_project_dir(slug)
    results_dir = project_dir / "results"
    if not results_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for f in sorted(results_dir.iterdir(), reverse=True):
        if not f.is_file() or not f.name.endswith(".json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            runs.append({
                "file": f.name,
                "tool_id": data.get("tool_id", ""),
                "timestamp": data.get("timestamp", ""),
                "exit_code": data.get("exit_code", -1),
            })
        except (json.JSONDecodeError, OSError):
            continue

    return runs
