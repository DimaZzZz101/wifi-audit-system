"""Containers API: проксирование в TOOL-manager с JWT. Аудит в Gateway. Реестр - только образы WiFi Audit."""
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_user, audit, get_bearer_token
from app.models.user import User
from app.schemas.containers import (
    ContainerCreate,
    ContainerItem,
    ContainerCreated,
    ContainerStopped,
    ImageItem,
)
from app.services import tool_manager_client
from app.services.registry_service import (
    get_registry_allow_list_from_tools,
    get_matching_registry_reference,
    image_matches_registry,
    is_image_reference_in_registry,
)

router = APIRouter(prefix="/containers", tags=["containers"])


@router.get(
    "",
    response_model=list[ContainerItem],
    summary="Список управляемых контейнеров",
    description="""
    Возвращает список контейнеров, созданных через TOOL-manager (с меткой `wifiaudit.managed=1`).

    Запрос проксируется в TOOL-manager с передачей JWT токена пользователя.
    Действие логируется в аудит-лог.
    """,
    responses={
        200: {"description": "Список контейнеров"},
        401: {"description": "Токен отсутствует или невалиден"},
        503: {"description": "TOOL-manager недоступен"},
    },
)
async def containers_list(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    all: bool = False,
) -> list[ContainerItem]:
    """
    Получить список управляемых контейнеров.

    **Query параметры:**
    - `all` (bool, default: false): включить остановленные контейнеры

    **Пример ответа:**
    ```json
    [
      {
        "id": "abc123...",
        "short_id": "abc123",
        "name": "nmap-scan",
        "image": "nmap/nmap:latest",
        "status": "running",
        "created": "2026-02-04T10:00:00Z",
        "labels": {"wifiaudit.managed": "1"}
      }
    ]
    ```
    """
    token = get_bearer_token(request)
    try:
        items = await tool_manager_client.tool_manager_list_containers(token, all_containers=all)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text or str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TOOL-manager unavailable")
    return [ContainerItem(**x) for x in items]


@router.get(
    "/images",
    response_model=list[ImageItem],
    summary="Реестр образов WiFi Audit",
    description="Образы, входящие в реестр WiFi Audit (служебные и инструментальные). Только образы из этого списка можно использовать при создании контейнеров.",
)
async def containers_images(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> list[ImageItem]:
    token = get_bearer_token(request)
    try:
        all_images = await tool_manager_client.tool_manager_list_images(token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text or str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TOOL-manager unavailable")
    allow_list = get_registry_allow_list_from_tools()
    filtered: list[dict] = []
    for x in all_images:
        if not image_matches_registry(x.get("tags") or [], allow_list):
            continue
        ref = get_matching_registry_reference(x.get("tags") or [], allow_list)
        filtered.append({**x, "registry_reference": ref})
    return [ImageItem(**x) for x in filtered]


@router.get(
    "/{container_id}",
    response_model=ContainerItem,
    summary="Информация о контейнере",
    description="""
    Возвращает детальную информацию об одном управляемом контейнере по его ID.

    Запрос проксируется в TOOL-manager.
    """,
    responses={
        200: {"description": "Информация о контейнере"},
        401: {"description": "Токен отсутствует или невалиден"},
        404: {"description": "Контейнер не найден"},
        503: {"description": "TOOL-manager недоступен"},
    },
)
async def container_get(
    container_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> ContainerItem:
    """
    Получить информацию о контейнере по ID.

    **Параметры:**
    - `container_id` (str): ID контейнера (полный или короткий)

    **Пример ответа:**
    ```json
    {
      "id": "abc123...",
      "short_id": "abc123",
      "name": "nmap-scan",
      "image": "nmap/nmap:latest",
      "status": "running",
      "created": "2026-02-04T10:00:00Z",
      "labels": {"wifiaudit.managed": "1"}
    }
    ```
    """
    token = get_bearer_token(request)
    try:
        item = await tool_manager_client.tool_manager_get_container(token, container_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text or str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TOOL-manager unavailable")
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")
    return ContainerItem(**item)


@router.post(
    "",
    response_model=ContainerCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Создать контейнер",
    description="""
    Создаёт и запускает новый управляемый контейнер через TOOL-manager.

    Контейнер автоматически получает метку `wifiaudit.managed=1`.
    Действие логируется в аудит-лог с деталями (image, name, type).
    """,
    responses={
        201: {"description": "Контейнер создан и запущен"},
        401: {"description": "Токен отсутствует или невалиден"},
        400: {"description": "Неверные параметры запроса"},
        503: {"description": "TOOL-manager недоступен"},
    },
)
async def container_create(
    request: Request,
    body: ContainerCreate,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ContainerCreated:
    """
    Создать и запустить контейнер.

    **Пример запроса:**
    ```json
    {
      "image": "nmap/nmap:latest",
      "name": "nmap-scan",
      "container_type": "instrumental",
      "command": ["nmap", "-sS", "192.168.1.0/24"],
      "network_mode": "host",
      "cap_add": ["NET_RAW", "NET_ADMIN"]
    }
    ```

    **Пример ответа:**
    ```json
    {
      "id": "abc123...",
      "short_id": "abc123",
      "name": "nmap-scan",
      "image": "nmap/nmap:latest",
      "status": "running",
      "created": "2026-02-04T10:00:00Z"
    }
    ```
    """
    allow_list = get_registry_allow_list_from_tools()
    if not is_image_reference_in_registry(body.image, allow_list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Образ должен входить в реестр WiFi Audit. Используйте только образы из раздела "Реестр".',
        )
    token = get_bearer_token(request)
    try:
        result = await tool_manager_client.tool_manager_create_container(
            token,
            body.model_dump(exclude_none=True),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text or str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TOOL-manager unavailable")
    await audit(
        db,
        user_id=current_user.id,
        action="container.create",
        request=request,
        resource_type="container",
        resource_id=result.get("id") or result.get("short_id"),
        details={
            "image": body.image,
            "name": body.name,
            "type": body.container_type,
        },
    )
    await db.commit()
    return ContainerCreated(**result)


@router.delete(
    "/{container_id}",
    response_model=ContainerStopped,
    summary="Остановить контейнер",
    description="""
    Останавливает управляемый контейнер и при необходимости удаляет его.

    По умолчанию контейнер удаляется после остановки (`remove=true`).
    Действие логируется в аудит-лог.
    """,
    responses={
        200: {"description": "Контейнер остановлен"},
        401: {"description": "Токен отсутствует или невалиден"},
        403: {"description": "Доступ запрещён (не управляемый контейнер)"},
        404: {"description": "Контейнер не найден"},
        503: {"description": "TOOL-manager недоступен"},
    },
)
async def container_stop(
    container_id: str,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    remove: bool = True,
) -> ContainerStopped:
    """
    Остановить и удалить контейнер.

    **Параметры:**
    - `container_id` (str): ID контейнера
    - `remove` (bool, query, default: true): удалить контейнер после остановки

    **Пример ответа:**
    ```json
    {
      "id": "abc123...",
      "stopped": true,
      "removed": true
    }
    ```
    """
    token = get_bearer_token(request)
    try:
        result = await tool_manager_client.tool_manager_stop_container(token, container_id, remove=remove)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Container not found")
        if e.response.status_code == 403:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.response.text or str(e))
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text or str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TOOL-manager unavailable")
    await audit(
        db,
        user_id=current_user.id,
        action="container.stop",
        request=request,
        resource_type="container",
        resource_id=container_id,
        details={"remove": remove},
    )
    await db.commit()
    return ContainerStopped(**result)
