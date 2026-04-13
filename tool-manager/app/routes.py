"""REST API TOOL-manager: контейнеры и реестр образов. Все эндпоинты требуют JWT (Authorization: Bearer)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from docker.errors import NotFound

from app.deps import require_jwt
from app.schemas import (
    ContainerCreate,
    ContainerItem,
    ContainerCreated,
    ContainerStopped,
    ImageItem,
    ImagePullBody,
)
from app import container_service

router = APIRouter(prefix="/containers", tags=["containers"])


@router.get("/images", response_model=list[ImageItem])
async def images_list(
    _payload: Annotated[dict, Depends(require_jwt)],
) -> list[ImageItem]:
    """Все образы Docker (фильтр по реестру WiFi Audit применяется в API-Gateway)."""
    items = await container_service.list_images()
    return [ImageItem(**x) for x in items]


@router.post("/images/pull")
async def images_pull(
    body: ImagePullBody,
    _payload: Annotated[dict, Depends(require_jwt)],
) -> dict:
    """Выполнить docker pull образа. Body: { \"image\": \"name:tag\" }."""
    result = await container_service.pull_image(body.image.strip())
    if not result.get("pulled"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "docker pull failed"),
        )
    return result


@router.get("", response_model=list[ContainerItem])
async def containers_list(
    _payload: Annotated[dict, Depends(require_jwt)],
    all: bool = False,
) -> list[ContainerItem]:
    """Список управляемых контейнеров (label wifiaudit.managed=1)."""
    items = await container_service.list_containers(all=all)
    return [ContainerItem(**x) for x in items]


@router.get("/{container_id}", response_model=ContainerItem)
async def container_get(
    container_id: str,
    _payload: Annotated[dict, Depends(require_jwt)],
) -> ContainerItem:
    """Один контейнер по id."""
    item = await container_service.get_container(container_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")
    return ContainerItem(**item)


@router.post("", response_model=ContainerCreated, status_code=status.HTTP_201_CREATED)
async def container_create(
    body: ContainerCreate,
    _payload: Annotated[dict, Depends(require_jwt)],
) -> ContainerCreated:
    """Создать и запустить контейнер."""
    try:
        result = await container_service.create_container(
            image=body.image,
            name=body.name,
            container_type=body.container_type,
            env=body.env,
            network_mode=body.network_mode,
            cap_add=body.cap_add,
            volumes=body.volumes,
            command=body.command,
            detach=body.detach,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return ContainerCreated(**result)


@router.delete("/{container_id}", response_model=ContainerStopped)
async def container_stop(
    container_id: str,
    _payload: Annotated[dict, Depends(require_jwt)],
    remove: bool = True,
    stop_timeout: int = 10,
) -> ContainerStopped:
    """Остановить и при необходимости удалить контейнер."""
    stop_timeout = max(1, min(stop_timeout, 300))
    try:
        result = await container_service.stop_container(
            container_id, remove=remove, stop_timeout=stop_timeout,
        )
    except NotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return ContainerStopped(**result)
