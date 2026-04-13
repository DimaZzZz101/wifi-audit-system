"""API реестра образов WiFi Audit - только для чтения, образы из определений инструментов."""
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_bearer_token, require_user
from app.models.user import User
from app.services import tool_manager_client
from app.services.registry_service import (
    get_matching_registry_reference,
    get_registry_entries_from_tools,
)

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get(
    "",
    summary="Реестр образов (только для чтения)",
    description="Образы инструментов, автоматически из определений. Только эти образы можно использовать для запуска контейнеров в сессиях.",
)
async def registry_list(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> list[dict[str, Any]]:
    """Список образов реестра с информацией о наличии в Docker."""
    entries = get_registry_entries_from_tools()
    token = get_bearer_token(request)

    try:
        all_images = await tool_manager_client.tool_manager_list_images(token)
    except (httpx.HTTPStatusError, httpx.RequestError):
        all_images = []

    allow_list = [e["image_reference"] for e in entries]
    result: list[dict[str, Any]] = []

    for entry in entries:
        ref = entry["image_reference"]
        docker_match = None
        for img in all_images:
            tags = img.get("tags") or []
            matched_ref = get_matching_registry_reference(tags, [ref])
            if matched_ref:
                docker_match = img
                break

        item: dict[str, Any] = {
            **entry,
            "in_docker": docker_match is not None,
        }
        if docker_match:
            item["docker_id"] = docker_match.get("id", "")
            item["size"] = docker_match.get("size", 0)
            item["created"] = docker_match.get("created", "")
        result.append(item)

    return result
