"""Схемы для API проектов аудита."""
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """Тело запроса создания проекта."""
    name: str = Field(..., min_length=1, max_length=256, description="Название проекта")


class ProjectUpdate(BaseModel):
    """Тело запроса обновления проекта (PATCH)."""
    status: str | None = None
    name: str | None = None
    obfuscation_enabled: bool | None = None


class ProjectResponse(BaseModel):
    """Ответ с данными проекта."""
    id: int
    slug: str
    name: str
    created_at: datetime
    status: str
    session_type: str
    mac_filter_type: str | None = None
    mac_filter_entries: list[str] = []
    obfuscation_enabled: bool = False

    model_config = {"from_attributes": True}


class MacFilterBody(BaseModel):
    """Тело PUT /mac-filter."""
    filter_type: str | None = Field(None, pattern="^(whitelist|blacklist)$")
    entries: list[str] = Field(default_factory=list, max_length=10000)


class MacFilterResponse(BaseModel):
    filter_type: str | None = None
    entries: list[str] = []
