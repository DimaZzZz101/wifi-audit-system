"""REST API TOOL-manager: запуск короткоживущих tool-контейнеров (возврат stdout/stderr)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import require_jwt
from app import container_service

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolRunBody(BaseModel):
    image: str = Field(..., min_length=1)
    command: list[str] | None = None
    env: dict[str, str] | None = None
    network_mode: str | None = "host"
    cap_add: list[str] | None = None
    volumes: list[str] | None = None
    timeout: int = Field(60, ge=5, le=300)
    container_name: str | None = None
    labels: dict[str, str] | None = None


@router.post("/run")
async def tool_run(
    body: ToolRunBody,
    _payload: Annotated[dict, Depends(require_jwt)],
) -> dict[str, Any]:
    """
    Запустить короткоживущий контейнер (tool), дождаться завершения, вернуть stdout/stderr и exit_code.
    """
    result = await container_service.run_tool(
        image=body.image.strip(),
        command=body.command,
        env=body.env,
        network_mode=body.network_mode,
        cap_add=body.cap_add,
        volumes=body.volumes,
        timeout=body.timeout,
        name=body.container_name,
        extra_labels=body.labels,
    )
    return result
