"""Схемы API реестра образов WiFi Audit."""
from pydantic import BaseModel, Field


class RegistryAddRequest(BaseModel):
    """Добавить образ в реестр WiFi Audit."""
    image_reference: str = Field(..., min_length=1, max_length=512, description="Образ (name:tag)", example="busybox:latest")
    pull: bool = Field(False, description="Выполнить docker pull перед добавлением")


class RegistryAddResponse(BaseModel):
    """Ответ после добавления образа в реестр."""
    added: bool = True
    image_reference: str = Field(..., description="Добавленная ссылка на образ")


class RegistryRemoveResponse(BaseModel):
    """Ответ после удаления образа из реестра (образ в Docker не удаляется)."""
    removed: bool = True
    image_reference: str = Field(..., description="Удалённая из реестра ссылка")
