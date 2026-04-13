"""Metrics API: host + system containers (db, api, frontend, tool-manager). Excludes tool-manager-managed containers."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from app.api.deps import require_user, get_bearer_token
from app.models.user import User
from app.schemas.metrics import SystemMetrics
from app.services.metrics_service import get_system_metrics
from app.services.tool_manager_client import tool_manager_list_containers

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get(
    "/system",
    response_model=SystemMetrics,
    summary="Системные метрики",
    description="""
    Возвращает метрики хостовой системы и системных контейнеров.

    **Метрики хоста:**
    - CPU: процент использования процессора
    - Memory: использование RAM (MB, процент от общего объёма)
    - Disk: использование диска (GB, процент)

    **Системные контейнеры:**
    - db, api, frontend, tool-manager
    - Для каждого: CPU%, Memory (MB, лимит из docker-compose, процент), ID, имя

    Контейнеры, созданные через tool-manager (managed), исключаются из списка.
    Данные получаются из cAdvisor (готовый сборщик метрик).
    """,
    responses={
        200: {"description": "Метрики системы"},
        401: {"description": "Токен отсутствует или невалиден"},
    },
)
async def metrics_system(
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> SystemMetrics:
    """
    Получить метрики хоста и системных контейнеров.

    **Пример ответа:**
    ```json
    {
      "host": {
        "cpu_percent": 7.0,
        "memory_used_mb": 2158.1,
        "memory_limit_mb": 3867.6,
        "memory_percent": 55.8,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.06,
        "disk_percent": 0.0
      },
      "cpu": {"percent": 2.3, "containers_count": 4},
      "memory": {"used_mb": 171.8, "limit_mb": 15470.5, "percent": 1.1},
      "containers": [
        {
          "id": "docker-055c3",
          "name": "wifiaudit-tool-manager",
          "cpu_percent": 0.1,
          "memory_used_mb": 53.3,
          "memory_limit_mb": 256.0,
          "memory_percent": 20.8
        }
      ],
      "disk": {"used_gb": 0.0, "total_gb": 0.06, "percent": 0.0, "path": "/"}
    }
    ```
    """
    managed_ids: set[str] = set()
    token = get_bearer_token(request)
    if token:
        try:
            managed_list = await tool_manager_list_containers(token, all_containers=True)
            managed_ids = {c["id"] for c in managed_list if c.get("id")}
        except Exception:
            pass
    data = await get_system_metrics(managed_container_ids=managed_ids)
    return SystemMetrics(**data)
