"""Схемы API установки модулей и каталога доступных модулей."""
from pydantic import BaseModel, Field


class InstalledModule(BaseModel):
    """Установленный модуль (из каталога или системный)."""
    id: str
    name: str
    type: str
    description: str | None = None
    version: str | None = None
    author: str | None = None
    provides: list[str] = Field(default_factory=list)
    container: dict | None = None
    frontend: dict | None = None
    system: bool = False
    removable: bool = False


class AvailableModule(BaseModel):
    """Модуль из удалённого каталога (доступен для установки)."""
    id: str
    name: str
    version: str = ""
    description: str | None = None
    author: str | None = None
    download_url: str | None = None
    checksum: str | None = None


class ModuleDownloadRequest(BaseModel):
    """Запрос на скачивание модуля."""
    download_url: str = Field(..., description="URL пакета .tar.gz")


class ModuleInstallRequest(BaseModel):
    """Запрос на установку ранее скачанного модуля."""
    checksum: str | None = Field(None, description="SHA256 хеш пакета для проверки")


class ModuleInstallResponse(BaseModel):
    """Ответ после установки."""
    module_id: str


class ModuleDownloadStatus(BaseModel):
    """Статус скачивания."""
    success: bool
    path: str | None = None
