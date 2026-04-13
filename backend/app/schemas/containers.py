"""Container API schemas."""
from typing import Any

from pydantic import BaseModel, Field


class ContainerCreate(BaseModel):
    """Схема создания контейнера."""
    image: str = Field(..., min_length=1, description="Docker image name:tag", example="nmap/nmap:latest")
    name: str | None = Field(None, max_length=128, description="Имя контейнера (опционально)", example="nmap-scan")
    container_type: str | None = Field(None, max_length=32, description="Тип: service | instrumental", example="instrumental")
    env: dict[str, str] | None = Field(None, description="Переменные окружения", example={"TARGET": "192.168.1.0/24"})
    network_mode: str | None = Field("host", description="Режим сети Docker", example="host")
    cap_add: list[str] | None = Field(None, description="Дополнительные capabilities", example=["NET_RAW", "NET_ADMIN"])
    volumes: list[str] | None = Field(None, description="Тома: host_path:container_path или host_path", example=["/data:/app/data"])
    command: str | list[str] | None = Field(None, description="Команда запуска", example=["nmap", "-sS", "192.168.1.0/24"])
    detach: bool = Field(True, description="Запуск в фоновом режиме")


class ContainerItem(BaseModel):
    """Информация об управляемом контейнере."""
    id: str = Field(..., description="Полный ID контейнера", example="abc123def456...")
    short_id: str = Field(..., description="Короткий ID (12 символов)", example="abc123")
    name: str = Field(..., description="Имя контейнера", example="nmap-scan")
    image: str = Field(..., description="Образ Docker", example="nmap/nmap:latest")
    status: str = Field(..., description="Статус контейнера", example="running")
    created: str = Field(..., description="Время создания (ISO 8601)", example="2026-02-04T10:00:00Z")
    labels: dict[str, str] | None = Field(None, description="Метки контейнера", example={"wifiaudit.managed": "1"})


class ContainerCreated(BaseModel):
    id: str | None = None
    short_id: str | None = None
    name: str | None = None
    image: str
    status: str
    created: str | None = None


class ContainerStopped(BaseModel):
    id: str
    stopped: bool = True
    removed: bool = True


class ImageItem(BaseModel):
    """Образ из реестра Docker (страница Реестр)."""
    id: str = Field(..., description="Короткий ID образа")
    tags: list[str] = Field(default_factory=list, description="Теги образа (image:tag)")
    created: str = Field("", description="Время создания")
    size: int = Field(0, description="Размер в байтах")
    registry_reference: str | None = Field(None, description="Ссылка из реестра WiFi Audit для удаления")
