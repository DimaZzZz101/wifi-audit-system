"""Схемы API плагинов (манифест на диске)."""
from pydantic import BaseModel, Field


class PluginContainer(BaseModel):
    """Container run config for instrumental/service modules."""
    image: str | None = None
    type: str = "instrumental"  # instrumental | service
    default_command: str | list[str] | None = None


class PluginFrontend(BaseModel):
    """Optional frontend bundle (UMD) URL for dynamic loading."""
    bundle_url: str | None = None


class PluginDescriptor(BaseModel):
    """Дескриптор плагина (JSON-манифест)."""
    id: str = Field(..., description="Уникальный идентификатор плагина", example="system_metrics")
    name: str = Field(..., description="Название плагина", example="System Metrics")
    type: str = Field(..., description="Тип: system | instrumental | service", example="system")
    description: str | None = Field(None, description="Описание плагина", example="Host (RAM, CPU, DISK) + system containers")
    version: str | None = Field(None, description="Версия плагина", example="1.0.0")
    author: str | None = Field(None, description="Автор плагина")
    provides: list[str] = Field(default_factory=list, description="Список возможностей (capabilities)", example=["status_tiles"])
    container: PluginContainer | None = Field(None, description="Конфигурация контейнера (если запускается как контейнер)")
    frontend: PluginFrontend | None = Field(None, description="Конфигурация фронтенда (если есть UI компонент)")
