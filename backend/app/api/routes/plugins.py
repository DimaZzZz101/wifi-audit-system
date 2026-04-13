"""API плагинов: список и получение по id. Требуется аутентификация."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.api.deps import require_user
from app.config import get_settings
from app.models.user import User
from app.schemas.plugins import PluginDescriptor
from app.plugins.registry import list_plugins, get_plugin

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _plugins_dir() -> str:
    return get_settings().plugins_dir or ""


@router.get(
    "",
    response_model=list[PluginDescriptor],
    summary="Список плагинов",
    description="""
    Возвращает список зарегистрированных плагинов.

    Плагины могут предоставлять различные возможности (capabilities):
    - `status_tiles`: плитки для страницы Статус (например, System Metrics)
    - `container_runnable`: можно запустить как контейнер

    Используйте параметр `provides` для фильтрации по возможностям.
    """,
    responses={
        200: {"description": "Список плагинов"},
        401: {"description": "Токен отсутствует или невалиден"},
    },
)
async def plugins_list(
    current_user: Annotated[User, Depends(require_user)],
    provides: str | None = Query(None, description="Фильтр по возможности, например: status_tiles"),
) -> list[PluginDescriptor]:
    """
    Получить список плагинов.

    **Query параметры:**
    - `provides` (str, optional): фильтр по возможности (например, `status_tiles`)

    **Пример ответа:**
    ```json
    [
      {
        "id": "system_metrics",
        "name": "System Metrics",
        "type": "system",
        "description": "Host (RAM, CPU, DISK) + system containers",
        "version": "1.0.0",
        "provides": ["status_tiles"],
        "container": null,
        "frontend": null
      }
    ]
    ```
    """
    items = list_plugins(provides=provides, plugins_dir=_plugins_dir())
    return [PluginDescriptor.model_validate(_plugin_to_response(p)) for p in items]


@router.get(
    "/{plugin_id}",
    response_model=PluginDescriptor,
    summary="Информация о плагине",
    description="""
    Возвращает детальную информацию об одном плагине по его ID.

    Плагины могут быть встроенными (system) или загруженными из каталога `PLUGINS_DIR`.
    """,
    responses={
        200: {"description": "Информация о плагине"},
        401: {"description": "Токен отсутствует или невалиден"},
        404: {"description": "Плагин не найден"},
    },
)
async def plugin_get(
    plugin_id: str,
    current_user: Annotated[User, Depends(require_user)],
) -> PluginDescriptor:
    """
    Получить информацию о плагине по ID.

    **Параметры:**
    - `plugin_id` (str): ID плагина

    **Пример ответа:**
    ```json
    {
      "id": "system_metrics",
      "name": "System Metrics",
      "type": "system",
      "description": "Host (RAM, CPU, DISK) + system containers",
      "version": "1.0.0",
      "provides": ["status_tiles"],
      "container": null,
      "frontend": null
    }
    ```
    """
    plugin = get_plugin(plugin_id, plugins_dir=_plugins_dir())
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return PluginDescriptor.model_validate(_plugin_to_response(plugin))


def _plugin_to_response(p: dict) -> dict:
    """Map internal plugin dict to API response (PluginDescriptor)."""
    return {
        "id": p["id"],
        "name": p["name"],
        "type": p["type"],
        "description": p.get("description"),
        "version": p.get("version"),
        "author": p.get("author"),
        "provides": p.get("provides") or [],
        "container": p.get("container"),
        "frontend": p.get("frontend"),
    }
