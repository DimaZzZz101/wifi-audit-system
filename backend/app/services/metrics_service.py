"""Системные метрики: cAdvisor (хост + контейнеры). Хост = root container; системные = db, api, frontend, tool-manager; managed исключаются."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

SYSTEM_METRICS_LABEL_KEY = "wifiaudit.metrics"
SYSTEM_METRICS_LABEL_VALUE = "system"
IGNORE_METRICS_LABEL_VALUE = "ignore"

_FALLBACK = {
    "host": {
        "cpu_percent": None,
        "memory_used_bytes": 0,
        "memory_limit_bytes": None,
        "memory_used_mb": 0.0,
        "memory_limit_mb": None,
        "memory_percent": None,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.0,
        "disk_percent": 0.0,
    },
    "cpu": {"percent": 0.0, "containers_count": 0},
    "memory": {
        "used_bytes": 0,
        "limit_bytes": 0,
        "used_mb": 0.0,
        "limit_mb": None,
        "percent": None,
    },
    "containers": [],
    "disk": {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0, "path": "/"},
    "source_ok": False,
    "errors": ["cadvisor_unavailable"],
}


def _cadvisor_base() -> str:
    return get_settings().cadvisor_url.rstrip("/")


def _system_container_names() -> set[str]:
    return {n.strip() for n in (get_settings().system_container_names or []) if n and n.strip()}


def _is_system_container(name: str, labels: dict[str, str] | None = None) -> bool:
    """Системный контейнер: приоритет label wifiaudit.metrics=system, fallback - exact name."""
    labels = labels or {}
    label_value = (labels.get(SYSTEM_METRICS_LABEL_KEY) or "").strip().lower()
    if label_value == SYSTEM_METRICS_LABEL_VALUE:
        return True
    if label_value == IGNORE_METRICS_LABEL_VALUE:
        return False
    return name in _system_container_names()


def _container_id_from_path(key: str) -> str:
    """Полный ID контейнера из пути cAdvisor (/docker/xxx)."""
    if key.startswith("/docker/"):
        return key.replace("/docker/", "").strip("/")
    return key.split("/")[-1] or ""


def _is_managed(container_path_or_id: str, managed_ids: set[str]) -> bool:
    """Контейнер создан tool-manager (есть в списке managed)."""
    if not managed_ids:
        return False
    cid = _container_id_from_path(container_path_or_id)
    if cid in managed_ids:
        return True
    for mid in managed_ids:
        if mid.startswith(cid) or cid.startswith(mid):
            return True
    return False


def _display_name(cadvisor_key: str) -> str:
    """Имя для отображения (часть после /docker/)."""
    if cadvisor_key.startswith("/docker/"):
        return cadvisor_key.replace("/docker/", "").strip("/")
    return cadvisor_key.split("/")[-1] or "?"


def _safe_id(key: str) -> str:
    """Короткий id для ответа (12 символов или целиком)."""
    suffix = key.split("/")[-1] if "/" in key else key
    return suffix[:12] if len(suffix) > 12 else suffix


def _parse_cadvisor_summary_v2(
    summary: dict[str, Any],
    path_to_name: dict[str, str] | None = None,
    path_to_labels: dict[str, dict[str, str]] | None = None,
    managed_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[float], int, int]:
    """Из ответа cAdvisor v2 summary: только системные контейнеры (db, api, frontend, tool-manager); без managed."""
    containers_list: list[dict[str, Any]] = []
    cpu_percents: list[float] = []
    mem_used_total = 0
    mem_limit_total = 0
    managed_ids = managed_ids or set()
    path_to_labels = path_to_labels or {}

    for key, samples in summary.items():
        if not isinstance(key, str) or not key.startswith("/docker/"):
            continue
        if _is_managed(key, managed_ids):
            continue
        name = (path_to_name or {}).get(key) or _display_name(key)
        labels = path_to_labels.get(key, {})
        if not _is_system_container(name, labels):
            continue
        if not samples:
            continue
        try:
            s = samples[-1] if isinstance(samples, list) else samples
            if not isinstance(s, dict):
                continue
            lu = (s.get("latest_usage") or s) if isinstance(s.get("latest_usage"), dict) else (s if isinstance(s, dict) else {})
            cpu_val = lu.get("cpu") if lu else 0
            cpu_pct = round((float(cpu_val) / 10.0), 1) if isinstance(cpu_val, (int, float)) else None
            mem_bytes = lu.get("memory") if lu else 0
            if not isinstance(mem_bytes, (int, float)):
                mem_bytes = 0
            mem_limit = 0
            mem_pct = (mem_bytes / mem_limit * 100.0) if mem_limit and mem_limit > 0 else None
            used_mb = round(int(mem_bytes) / (1024 * 1024), 1)
            limit_mb = round(mem_limit / (1024 * 1024), 1) if mem_limit else None
            containers_list.append({
                "id": _safe_id(key),
                "name": name,
                "cpu_percent": cpu_pct,
                "memory_used_bytes": int(mem_bytes),
                "memory_limit_bytes": mem_limit if mem_limit else None,
                "memory_used_mb": used_mb,
                "memory_limit_mb": limit_mb,
                "memory_percent": round(mem_pct, 1) if mem_pct is not None else None,
            })
            if cpu_pct is not None:
                cpu_percents.append(cpu_pct)
            mem_used_total += int(mem_bytes)
            if mem_limit:
                mem_limit_total += mem_limit
        except (TypeError, ValueError, KeyError):
            continue

    return containers_list, cpu_percents, mem_used_total, mem_limit_total


def _flatten_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """cAdvisor 0.56 может вернуть вложенный формат: один ключ (docker) -> карта контейнеров."""
    if not summary or len(summary) != 1:
        return summary
    only_val = next(iter(summary.values()))
    if isinstance(only_val, dict):
        for k in only_val:
            if isinstance(k, str) and k.startswith("/docker/"):
                return only_val
    return summary


def _is_path_like_key(key: str) -> bool:
    """Ключ похож на путь контейнера cAdvisor."""
    return isinstance(key, str) and (
        key.startswith("/docker/") or key.startswith("/system.") or key.startswith("/")
    )


def _flatten_to_path_map(data: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно найти уровень, где ключи - пути контейнеров (/docker/..., /system.slice/...)."""
    if not data or not isinstance(data, dict):
        return data
    # Уже плоский: есть хотя бы один ключ-путь
    for k in data:
        if _is_path_like_key(k):
            return data
    # Копаем вглубь: один или несколько вложенных dict
    for v in data.values():
        if isinstance(v, dict):
            inner = _flatten_to_path_map(v)
            if inner and inner is not v:
                return inner
    return data


def _flatten_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """cAdvisor может вернуть stats вложенно (docker -> subcontainers -> path -> samples)."""
    return _flatten_to_path_map(stats) or stats


def _docker_id_from_path(path: str) -> str | None:
    """Из пути cAdvisor извлечь ID контейнера Docker (для сопоставления spec и stats)."""
    if not path:
        return None
    # /system.slice/docker-<id>.scope или /docker/<id>
    if path.startswith("/docker/"):
        return path.replace("/docker/", "").strip("/")
    segment = path.rstrip("/").split("/")[-1] or ""
    if segment.startswith("docker-") and segment.endswith(".scope"):
        return segment[7:-7]  # docker- ... .scope
    return None


def _build_path_to_name_from_spec(spec: dict[str, Any]) -> dict[str, str]:
    """Построить путь cgroup -> имя контейнера по ответу /api/v2.0/spec.

    На современных системах (cgroup v2, systemd) cAdvisor возвращает ключи вида
    '/system.slice/docker-<id>.scope' или вложенно (docker -> subcontainers -> path).
    Имя контейнера в aliases. Stats может возвращать /docker/<id> - добавляем оба ключа.
    """
    result: dict[str, str] = {}
    if not isinstance(spec, dict):
        return result
    spec = _flatten_to_path_map(spec) or spec

    def add(path: str, value: Any) -> None:
        norm_path = path if path.startswith("/") else f"/{path}"
        if isinstance(value, list) and value and isinstance(value[0], dict):
            value = value[0]
        name = norm_path.split("/")[-1] or ""
        if isinstance(value, dict):
            aliases = value.get("aliases") or value.get("Aliases") or []
            if isinstance(aliases, list) and aliases:
                first = aliases[0]
                if isinstance(first, str) and first:
                    name = first.strip("/").split("/")[-1] or name
        result[norm_path] = name
        # Чтобы stats с ключом /docker/<id> находил имя, добавляем альтернативный ключ
        docker_id = _docker_id_from_path(norm_path)
        if docker_id and name:
            result[f"/docker/{docker_id}"] = name

    for path, value in spec.items():
        if isinstance(path, str):
            add(path, value)
        if isinstance(path, str) and path == "docker" and isinstance(value, dict):
            for sub_path, sub_value in value.items():
                if isinstance(sub_path, str):
                    add(sub_path, sub_value)
    return result


def _build_path_to_labels_from_spec(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Построить путь cgroup -> labels контейнера по ответу /api/v2.0/spec."""
    result: dict[str, dict[str, str]] = {}
    if not isinstance(spec, dict):
        return result
    spec = _flatten_to_path_map(spec) or spec

    def add(path: str, value: Any) -> None:
        norm_path = path if path.startswith("/") else f"/{path}"
        if isinstance(value, list) and value and isinstance(value[0], dict):
            value = value[0]
        labels: dict[str, str] = {}
        if isinstance(value, dict):
            raw_labels = value.get("labels") or value.get("Labels") or {}
            if isinstance(raw_labels, dict):
                for k, v in raw_labels.items():
                    if isinstance(k, str) and isinstance(v, str):
                        labels[k] = v
        result[norm_path] = labels
        docker_id = _docker_id_from_path(norm_path)
        if docker_id:
            result[f"/docker/{docker_id}"] = labels

    for path, value in spec.items():
        if isinstance(path, str):
            add(path, value)
        if isinstance(path, str) and path == "docker" and isinstance(value, dict):
            for sub_path, sub_value in value.items():
                if isinstance(sub_path, str):
                    add(sub_path, sub_value)
    return result


def _build_path_to_memory_limit_from_spec(spec: dict[str, Any]) -> dict[str, int]:
    """Построить путь cgroup -> лимит памяти (bytes) по ответу /api/v2.0/spec.

    В spec есть memory.limit для каждого контейнера (из docker-compose mem_limit).
    Добавляем ключ /docker/<id> для совместимости со stats.
    """
    result: dict[str, int] = {}
    if not isinstance(spec, dict):
        return result
    spec = _flatten_to_path_map(spec) or spec

    def add(path: str, value: Any) -> None:
        norm_path = path if path.startswith("/") else f"/{path}"
        if isinstance(value, list) and value and isinstance(value[0], dict):
            value = value[0]
        if isinstance(value, dict):
            mem = value.get("memory") or value.get("Memory") or {}
            if isinstance(mem, dict):
                limit = mem.get("limit") or mem.get("Limit")
                if isinstance(limit, (int, float)) and limit > 0:
                    result[norm_path] = int(limit)
                    docker_id = _docker_id_from_path(norm_path)
                    if docker_id:
                        result[f"/docker/{docker_id}"] = int(limit)

    for path, value in spec.items():
        if isinstance(path, str):
            add(path, value)
        if isinstance(path, str) and path == "docker" and isinstance(value, dict):
            for sub_path, sub_value in value.items():
                if isinstance(sub_path, str):
                    add(sub_path, sub_value)
    return result


def _parse_cadvisor_stats_v2(
    stats: dict[str, Any],
    path_to_name: dict[str, str] | None = None,
    path_to_labels: dict[str, dict[str, str]] | None = None,
    managed_ids: set[str] | None = None,
    *,
    path_to_memory_limit: dict[str, int] | None = None,
    host_mem_limit: int = 0,
    num_cores: int = 0,
) -> tuple[list[dict[str, Any]], list[float], int, int]:
    """Парсинг v2.0 /stats?type=docker&recursive=true: системные контейнеры без managed.

    CPU% считаем по дельте двух последних сэмплов cpu.usage.total, нормируя на время и число ядер.
    MEM% - по лимиту из spec (docker-compose mem_limit), если есть, иначе от памяти хоста.
    """
    containers_list: list[dict[str, Any]] = []
    cpu_percents: list[float] = []
    mem_used_total = 0
    mem_limit_total = 0
    path_to_name = path_to_name or {}
    path_to_labels = path_to_labels or {}
    path_to_memory_limit = path_to_memory_limit or {}
    managed_ids = managed_ids or set()

    for path, samples in stats.items():
        if not isinstance(path, str):
            continue
        if _is_managed(path, managed_ids):
            continue
        name = path_to_name.get(path) or _display_name(path)
        labels = path_to_labels.get(path, {})
        if not _is_system_container(name, labels):
            continue
        if not isinstance(samples, list) or not samples:
            continue
        try:
            # stats: список сэмплов по времени, нас интересуют два последних
            latest = samples[-1]
            prev = samples[-2] if len(samples) > 1 else None
            if not isinstance(latest, dict):
                continue

            # CPU
            cpu_pct: float | None = None
            if prev and isinstance(prev, dict):
                try:
                    latest_cpu = int((latest.get("cpu") or {}).get("usage", {}).get("total") or 0)
                    prev_cpu = int((prev.get("cpu") or {}).get("usage", {}).get("total") or 0)
                    delta_cpu = max(latest_cpu - prev_cpu, 0)

                    latest_ts = latest.get("timestamp")
                    prev_ts = prev.get("timestamp")
                    if isinstance(latest_ts, str) and isinstance(prev_ts, str) and latest_ts != prev_ts:
                        # ISO8601 -> наносекунды считать сложно без парсинга дат, используем дельту "наносекунд" если есть
                        # но в stats есть cpu.usage.per_cpu_usage/usage.total с накоплением по времени,
                        # поэтому используем упрощённую формулу: доля от одного ядра за интервал,
                        # нормированная на число ядер.
                        # Здесь берём условную "нормировку" как 1e9 нс на ядро.
                        denom = 1e9 * max(num_cores or 1, 1)
                        cpu_pct = round((delta_cpu / denom) * 100.0, 1) if delta_cpu > 0 else 0.0
                except (TypeError, ValueError):
                    cpu_pct = None

            # Memory
            mem = latest.get("memory") or {}
            usage = int(mem.get("usage") or 0)
            # Приоритет: лимит из spec (docker-compose) > лимит из stats > лимит хоста
            limit_from_stats = int(mem.get("limit") or 0)
            limit_from_spec = path_to_memory_limit.get(path, 0)
            eff_limit = (
                limit_from_spec
                if limit_from_spec > 0
                else (limit_from_stats if limit_from_stats > 0 else (host_mem_limit or 0))
            )
            mem_pct = (usage / eff_limit * 100.0) if eff_limit and eff_limit > 0 else None
            used_mb = round(usage / (1024 * 1024), 1)
            limit_mb = round(eff_limit / (1024 * 1024), 1) if eff_limit else None
            containers_list.append(
                {
                    "id": _safe_id(path),
                    "name": name,
                    "cpu_percent": cpu_pct,
                    "memory_used_bytes": usage,
                    "memory_limit_bytes": int(eff_limit) if eff_limit else None,
                    "memory_used_mb": used_mb,
                    "memory_limit_mb": limit_mb,
                    "memory_percent": round(mem_pct, 1) if mem_pct is not None else None,
                }
            )
            if cpu_pct is not None:
                cpu_percents.append(cpu_pct)
            mem_used_total += usage
            if eff_limit:
                mem_limit_total += eff_limit
        except (TypeError, ValueError, KeyError):
            continue

    return containers_list, cpu_percents, mem_used_total, mem_limit_total


def _parse_root_summary(root_data: dict[str, Any]) -> tuple[float | None, int]:
    """Метрики хоста из root container (/) cAdvisor. Возвращает (cpu_percent, memory_used_bytes)."""
    cpu_percent: float | None = None
    mem_used = 0
    # Ответ может быть { "/": [summary] } или вложенный по ключу
    for key in ("/", "root", ""):
        val = root_data.get(key) if isinstance(root_data, dict) else None
        if val is None:
            continue
        samples = val if isinstance(val, list) else [val]
        if not samples:
            continue
        s = samples[-1] if isinstance(samples[-1], dict) else None
        if not s:
            continue
        lu = s.get("latest_usage") or s
        if isinstance(lu, dict):
            cpu_val = lu.get("cpu")
            if isinstance(cpu_val, (int, float)):
                cpu_percent = round(float(cpu_val) / 10.0, 1)
            mem_val = lu.get("memory")
            if isinstance(mem_val, (int, float)):
                mem_used = int(mem_val)
        break
    return cpu_percent, mem_used


def _disk_from_machine(machine: dict[str, Any]) -> tuple[float, float, float]:
    """Из MachineInfo взять диск (root fs). Возвращает used_gb, total_gb, percent."""
    fs_list = machine.get("filesystems") or machine.get("Filesystems") or []
    if not isinstance(fs_list, list):
        return 0.0, 0.0, 0.0
    for fs in fs_list:
        if not isinstance(fs, dict):
            continue
        try:
            capacity = int(fs.get("capacity") or fs.get("Capacity") or 0)
            if capacity <= 0:
                continue
            used = int(fs.get("usage") or fs.get("Usage") or 0)
            if used == 0:
                available = int(fs.get("available") or fs.get("Available") or 0)
                used = capacity - available if available else 0
            total_gb = capacity / (1024**3)
            used_gb = used / (1024**3)
            percent = (used / capacity * 100.0) if capacity else 0.0
            return round(used_gb, 2), round(total_gb, 2), round(percent, 1)
        except (TypeError, ValueError):
            continue
    return 0.0, 0.0, 0.0


def _disk_from_artifacts_path(path: str) -> tuple[float, float, float]:
    """Метрики диска по каталогу системного хранилища артефактов."""
    p = Path(path)
    if not p.exists():
        return 0.0, 0.0, 0.0
    usage = shutil.disk_usage(p)
    if usage.total <= 0:
        return 0.0, 0.0, 0.0
    total_gb = usage.total / (1024**3)
    used_gb = usage.used / (1024**3)
    percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
    return round(used_gb, 2), round(total_gb, 2), round(percent, 1)


async def get_system_metrics(managed_container_ids: set[str] | None = None) -> dict[str, Any]:
    """Собрать метрики из cAdvisor. Системные контейнеры = db, api, frontend, tool-manager; контейнеры tool-manager (managed) исключаются.

    CPU по контейнерам считаем по дельте двух последних сэмплов, MEM% - по лимиту из spec
    (docker-compose mem_limit), если его нет - из stats, иначе относительно памяти хоста.
    """
    base = _cadvisor_base()
    managed_container_ids = managed_container_ids or set()
    containers_list: list[dict[str, Any]] = []
    cpu_percents: list[float] = []
    mem_used = 0
    mem_limit = 0
    artifacts_path = get_settings().artifacts_dir
    disk_used_gb, disk_total_gb, disk_percent = _disk_from_artifacts_path(artifacts_path)
    host_cpu_percent: float | None = None
    host_mem_used = 0
    host_mem_limit = 0
    num_cores = 0
    errors: list[str] = []
    if disk_total_gb == 0.0:
        errors.append("artifacts_path_unavailable")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Machine: память хоста, диски, количество ядер
            machine: dict[str, Any] | None = None
            try:
                r_machine = await client.get(f"{base}/api/v2.0/machine")
                if r_machine.status_code == 200:
                    machine = r_machine.json()
                    mem_cap = machine.get("memory_capacity") or machine.get("MemoryCapacity") or 0
                    if mem_cap:
                        try:
                            host_mem_limit = int(mem_cap)
                        except (TypeError, ValueError):
                            host_mem_limit = 0
                    # DISK считаем по artifacts volume. Если путь недоступен - fallback на machine info.
                    if disk_total_gb == 0.0:
                        disk_used_gb, disk_total_gb, disk_percent = _disk_from_machine(machine)
                        if disk_total_gb > 0 and "artifacts_path_unavailable" in errors:
                            errors.remove("artifacts_path_unavailable")
                    num_cores = int(machine.get("num_cores") or machine.get("NumCores") or 0)
            except Exception:
                machine = None
                errors.append("cadvisor_machine_request_failed")

            # 2. Спецификация: cgroup path -> имя контейнера и лимит памяти (из docker-compose)
            path_to_name: dict[str, str] = {}
            path_to_labels: dict[str, dict[str, str]] = {}
            path_to_memory_limit: dict[str, int] = {}
            try:
                r_spec = await client.get(f"{base}/api/v2.0/spec", params={"type": "docker", "recursive": "true"})
                if r_spec.status_code == 200:
                    spec_raw = r_spec.json()
                    if isinstance(spec_raw, dict):
                        path_to_name = _build_path_to_name_from_spec(spec_raw)
                        path_to_labels = _build_path_to_labels_from_spec(spec_raw)
                        path_to_memory_limit = _build_path_to_memory_limit_from_spec(spec_raw)
                else:
                    errors.append(f"cadvisor_spec_http_{r_spec.status_code}")
            except Exception:
                errors.append("cadvisor_spec_request_failed")

            # 3. Основной источник данных по контейнерам: /api/v2.0/stats?type=docker&recursive=true&count=2
            try:
                r_stats = await client.get(
                    f"{base}/api/v2.0/stats",
                    params={"type": "docker", "recursive": "true", "count": "2"},
                )
                if r_stats.status_code == 200:
                    stats_data = r_stats.json()
                    if isinstance(stats_data, dict):
                        stats_flat = _flatten_stats(stats_data)
                        containers_list, cpu_percents, mem_used, mem_limit = _parse_cadvisor_stats_v2(
                            stats_flat,
                            path_to_name,
                            path_to_labels,
                            managed_container_ids,
                            path_to_memory_limit=path_to_memory_limit,
                            host_mem_limit=host_mem_limit,
                            num_cores=num_cores,
                        )
                else:
                    errors.append(f"cadvisor_stats_http_{r_stats.status_code}")
            except Exception:
                errors.append("cadvisor_stats_request_failed")

            # 4. Метрики хоста: root container (/) = вся машина (cAdvisor API).
            try:
                r_root = await client.get(f"{base}/api/v2.0/summary/", params={"type": "name"})
                if r_root.status_code == 200:
                    root_data = r_root.json()
                    host_cpu_percent, host_mem_used = _parse_root_summary(root_data)
                else:
                    errors.append(f"cadvisor_root_http_{r_root.status_code}")
            except Exception:
                errors.append("cadvisor_root_request_failed")

            # Если лимит памяти для агрегата контейнеров не определён - используем память хоста.
            if mem_limit == 0 and host_mem_limit:
                mem_limit = host_mem_limit
    except Exception:
        return _FALLBACK.copy()

    cpu_aggregate = sum(cpu_percents) if cpu_percents else 0.0
    mem_percent = (mem_used / mem_limit * 100.0) if mem_limit and mem_limit > 0 else None
    host_mem_percent = (
        (host_mem_used / host_mem_limit * 100.0) if host_mem_limit and host_mem_limit > 0 else None
    )

    return {
        "host": {
            "cpu_percent": host_cpu_percent,
            "memory_used_bytes": host_mem_used,
            "memory_limit_bytes": host_mem_limit if host_mem_limit else None,
            "memory_used_mb": round(host_mem_used / (1024 * 1024), 1),
            "memory_limit_mb": round(host_mem_limit / (1024 * 1024), 1) if host_mem_limit else None,
            "memory_percent": round(host_mem_percent, 1) if host_mem_percent is not None else None,
            "disk_used_gb": disk_used_gb,
            "disk_total_gb": disk_total_gb,
            "disk_percent": disk_percent,
        },
        "cpu": {
            "percent": round(cpu_aggregate, 1),
            "containers_count": len(containers_list),
        },
        "memory": {
            "used_bytes": int(mem_used),
            "limit_bytes": int(mem_limit),
            "used_mb": round(mem_used / (1024 * 1024), 1),
            "limit_mb": round(mem_limit / (1024 * 1024), 1) if mem_limit else None,
            "percent": round(mem_percent, 1) if mem_percent is not None else None,
        },
        "containers": containers_list,
        "disk": {
            "used_gb": disk_used_gb,
            "total_gb": disk_total_gb,
            "percent": disk_percent,
            "path": artifacts_path,
        },
        "source_ok": len(errors) == 0,
        "errors": errors,
    }
