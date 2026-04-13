"""Управление контейнерами через Docker SDK. Единственный сервис с доступом к docker.sock."""
import os
import asyncio
from typing import Any

import docker
from docker.errors import NotFound, ImageNotFound

MANAGED_LABEL = "wifiaudit.managed"
MANAGED_VALUE = "1"
DOCKER_SOCKET = "unix:///var/run/docker.sock"

# urllib3 не поддерживает схему http+docker; docker-py при unix:// ставит base_url=http+docker://localhost
# и может читать DOCKER_HOST из окружения. Принудительно unix, чтобы с хоста не просочился http+docker.
os.environ["DOCKER_HOST"] = DOCKER_SOCKET


def _get_client() -> docker.DockerClient:
    return docker.DockerClient(base_url=DOCKER_SOCKET)


async def list_containers(all: bool = False) -> list[dict[str, Any]]:
    def _run() -> list[dict[str, Any]]:
        client = _get_client()
        try:
            containers = client.containers.list(
                all=all,
                filters={"label": f"{MANAGED_LABEL}={MANAGED_VALUE}"},
            )
            result = []
            for c in containers:
                try:
                    img = c.image
                    image_name = img.tags[0] if img.tags else img.short_id
                except (ImageNotFound, Exception):
                    image_name = c.attrs.get("Config", {}).get("Image", "unknown")
                result.append({
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": c.name,
                    "image": image_name,
                    "status": c.status,
                    "created": c.attrs["Created"],
                    "labels": c.labels,
                })
            return result
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def create_container(
    image: str,
    *,
    name: str | None = None,
    container_type: str | None = None,
    env: dict[str, str] | None = None,
    network_mode: str | None = "host",
    cap_add: list[str] | None = None,
    volumes: list[str] | None = None,
    command: str | list[str] | None = None,
    detach: bool = True,
) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        client = _get_client()
        try:
            labels = {MANAGED_LABEL: MANAGED_VALUE}
            if container_type:
                labels["wifiaudit.type"] = container_type
            env_list = [f"{k}={v}" for k, v in (env or {}).items()]
            volumes_dict: dict[str, dict] = {}
            if volumes:
                for v in volumes:
                    parts = v.split(":")
                    if len(parts) >= 3:
                        host_p, container_p, mode = parts[0], parts[1], parts[2]
                        volumes_dict[host_p] = {"bind": container_p, "mode": mode}
                    elif len(parts) == 2:
                        volumes_dict[parts[0]] = {"bind": parts[1], "mode": "rw"}
                    else:
                        volumes_dict[v] = {"bind": v, "mode": "rw"}
            container = client.containers.run(
                image,
                name=name,
                command=command,
                environment=env_list or None,
                labels=labels,
                detach=detach,
                remove=False,
                network_mode=network_mode or None,
                cap_add=cap_add or None,
                volumes=volumes_dict if volumes_dict else None,
            )
            if detach and container:
                c = client.containers.get(container.id)
                return {
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": c.name,
                    "image": image,
                    "status": c.status,
                    "created": c.attrs["Created"],
                }
            return {"id": None, "status": "exited"}
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def stop_container(
    container_id: str,
    remove: bool = True,
    stop_timeout: int = 10,
) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        client = _get_client()
        try:
            c = client.containers.get(container_id)
            if c.labels.get(MANAGED_LABEL) != MANAGED_VALUE:
                raise ValueError("Container not managed by this system")
            c.stop(timeout=max(1, stop_timeout))
            if remove:
                c.remove()
            return {"id": container_id, "stopped": True, "removed": remove}
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def list_images() -> list[dict[str, Any]]:
    """Список образов (реестр - образы, которые может запускать tool-manager)."""
    def _run() -> list[dict[str, Any]]:
        client = _get_client()
        try:
            images = client.images.list()
            result: list[dict[str, Any]] = []
            for img in images:
                repoTags = [t for t in (img.attrs.get("RepoTags") or []) if t and t != "<none>:<none>"]
                if not repoTags:
                    continue
                result.append({
                    "id": img.short_id,
                    "tags": repoTags,
                    "created": img.attrs.get("Created", ""),
                    "size": img.attrs.get("Size", 0),
                })
            return sorted(result, key=lambda x: (x["tags"][0] if x["tags"] else "").lower())
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def pull_image(image: str) -> dict[str, Any]:
    """Выполнить docker pull. Возвращает результат в виде {'pulled': True, 'image': image} или ошибку."""
    def _run() -> dict[str, Any]:
        client = _get_client()
        try:
            client.images.pull(image)
            return {"pulled": True, "image": image}
        except Exception as e:
            return {"pulled": False, "image": image, "error": str(e)}
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def run_tool(
    image: str,
    command: list[str] | str | None = None,
    *,
    env: dict[str, str] | None = None,
    network_mode: str | None = "host",
    cap_add: list[str] | None = None,
    volumes: list[str] | None = None,
    timeout: int = 60,
    name: str | None = None,
    extra_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Запустить короткоживущий контейнер (tool), дождаться завершения, вернуть stdout/stderr и exit_code.
    Контейнер не получает label wifiaudit.managed и удаляется после выполнения.
    """
    def _run() -> dict[str, Any]:
        client = _get_client()
        container = None
        try:
            env_list = [f"{k}={v}" for k, v in (env or {}).items()]
            volumes_dict: dict[str, dict] = {}
            if volumes:
                for v in volumes:
                    parts = v.split(":")
                    if len(parts) >= 2:
                        host_p = parts[0]
                        container_p = parts[1]
                        mode = parts[2] if len(parts) > 2 else "ro"
                        volumes_dict[host_p] = {"bind": container_p, "mode": mode}
                    else:
                        volumes_dict[v] = {"bind": v, "mode": "ro"}
            labels = {"wifiaudit.tool": "1"}
            if extra_labels:
                labels.update(extra_labels)
            container = client.containers.run(
                image,
                name=name,
                command=command,
                environment=env_list or None,
                network_mode=network_mode or None,
                cap_add=cap_add or None,
                volumes=volumes_dict if volumes_dict else None,
                detach=True,
                remove=False,
                labels=labels,
            )
            if not container:
                return {"stdout": "", "stderr": "", "exit_code": -1}
            exit_code = container.wait(timeout=timeout).get("StatusCode", -1)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            container.remove(force=True)
            return {"stdout": logs, "stderr": "", "exit_code": exit_code}
        except Exception as e:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            return {"stdout": "", "stderr": str(e), "exit_code": -1}
        finally:
            client.close()

    return await asyncio.to_thread(_run)


async def get_container(container_id: str) -> dict[str, Any] | None:
    def _run() -> dict[str, Any] | None:
        client = _get_client()
        try:
            c = client.containers.get(container_id)
            if c.labels.get(MANAGED_LABEL) != MANAGED_VALUE:
                return None
            try:
                img = c.image
                image_name = img.tags[0] if img.tags else img.short_id
            except (ImageNotFound, Exception):
                image_name = c.attrs.get("Config", {}).get("Image", "unknown")
            return {
                "id": c.id,
                "short_id": c.short_id,
                "name": c.name,
                "image": image_name,
                "status": c.status,
                "created": c.attrs["Created"],
                "labels": c.labels,
            }
        except NotFound:
            return None
        finally:
            client.close()

    return await asyncio.to_thread(_run)
