"""Клиент TOOL-manager: проксирование запросов к контейнерам с JWT пользователя."""
from typing import Any

import httpx

from app.config import get_settings

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


def _base_url() -> str:
    return get_settings().tool_manager_url.rstrip("/")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def tool_manager_list_containers(token: str, all_containers: bool = False) -> list[dict[str, Any]]:
    """GET /containers?all=..."""
    url = f"{_base_url()}/containers"
    params = {} if not all_containers else {"all": "true"}
    resp = await _get_client().get(url, headers=_headers(token), params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def tool_manager_get_container(token: str, container_id: str) -> dict[str, Any] | None:
    """GET /containers/{id}. Returns None on 404."""
    url = f"{_base_url()}/containers/{container_id}"
    resp = await _get_client().get(url, headers=_headers(token), timeout=30.0)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def tool_manager_create_container(token: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /containers."""
    url = f"{_base_url()}/containers"
    resp = await _get_client().post(url, headers=_headers(token), json=body, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


async def tool_manager_stop_container(
    token: str,
    container_id: str,
    remove: bool = True,
    stop_timeout: int = 10,
) -> dict[str, Any]:
    """DELETE /containers/{id}?remove=...&stop_timeout=..."""
    url = f"{_base_url()}/containers/{container_id}"
    params: dict[str, str] = {
        "remove": "true" if remove else "false",
        "stop_timeout": str(max(1, stop_timeout)),
    }
    http_timeout = float(stop_timeout + 30)
    resp = await _get_client().delete(url, headers=_headers(token), params=params, timeout=http_timeout)
    resp.raise_for_status()
    return resp.json()


async def tool_manager_run_tool(
    token: str,
    image: str,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
    network_mode: str | None = "host",
    cap_add: list[str] | None = None,
    volumes: list[str] | None = None,
    timeout: int = 60,
    container_name: str | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST /tools/run - запуск короткоживущего tool-контейнера, возврат stdout/stderr/exit_code."""
    url = f"{_base_url()}/tools/run"
    body: dict[str, Any] = {"image": image, "timeout": timeout}
    if command is not None:
        body["command"] = command
    if env is not None:
        body["env"] = env
    if network_mode is not None:
        body["network_mode"] = network_mode
    if cap_add is not None:
        body["cap_add"] = cap_add
    if volumes is not None:
        body["volumes"] = volumes
    if container_name is not None:
        body["container_name"] = container_name
    if labels is not None:
        body["labels"] = labels
    resp = await _get_client().post(url, headers=_headers(token), json=body, timeout=float(timeout + 15))
    resp.raise_for_status()
    return resp.json()


async def tool_manager_list_images(token: str) -> list[dict[str, Any]]:
    """GET /containers/images - все образы Docker (без фильтра по реестру)."""
    url = f"{_base_url()}/containers/images"
    resp = await _get_client().get(url, headers=_headers(token), timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def tool_manager_pull_image(token: str, image: str) -> dict[str, Any]:
    """POST /containers/images/pull - docker pull образа."""
    url = f"{_base_url()}/containers/images/pull"
    resp = await _get_client().post(url, headers=_headers(token), json={"image": image}, timeout=300.0)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


async def tool_manager_hardware_summary(token: str, wifi_only: bool = False) -> dict[str, Any] | None:
    """
    GET /hardware/summary от TOOL-manager (хост: USB, PCI, интерфейсы, ФС).
    wifi_only=true - только Wi-Fi модули (USB/PCI). Возвращает None при ошибке/таймауте.
    """
    url = f"{_base_url()}/hardware/summary"
    params = {} if not wifi_only else {"wifi_only": "true"}
    try:
        resp = await _get_client().get(url, headers=_headers(token), params=params, timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None
