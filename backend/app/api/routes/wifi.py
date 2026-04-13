"""Модуль Wi-Fi: детальная информация об обнаруженных сетях. Данные собирает короткоживущий tool-контейнер."""
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_user, get_bearer_token
from app.config import get_settings
from app.models.user import User
from app.services import tool_manager_client

router = APIRouter(prefix="/wifi", tags=["wifi"])


@router.get(
    "/info",
    summary="Информация о Wi-Fi интерфейсах",
    description="Список беспроводных интерфейсов (iw dev). Собирается короткоживущим контейнером (tool) с network_mode: host.",
)
async def wifi_info(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    token = get_bearer_token(request)
    image = get_settings().wifi_tool_image
    try:
        result = await tool_manager_client.tool_manager_run_tool(
            token=token,
            image=image,
            command=None,
            network_mode="host",
            timeout=30,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Не удалось запустить Wi-Fi tool: {e}",
        )
    stdout = result.get("stdout") or ""
    exit_code = result.get("exit_code", -1)
    if exit_code != 0 and not stdout:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result.get("stderr") or "Wi-Fi tool завершился с ошибкой",
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = {"interfaces": [], "scans": {}, "raw": stdout[:2000]}
    return data
