"""Metrics API schemas."""
from pydantic import BaseModel, Field


class HostMetrics(BaseModel):
    """Метрики хостовой системы (RAM, CPU, DISK)."""
    cpu_percent: float | None = Field(None, description="Процент использования CPU хоста", example=7.0)
    memory_used_bytes: int = Field(0, description="Использование RAM в байтах", example=2262978560)
    memory_limit_bytes: int | None = Field(None, description="Общий объём RAM в байтах", example=4055506944)
    memory_used_mb: float = Field(0.0, description="Использование RAM в мегабайтах", example=2158.1)
    memory_limit_mb: float | None = Field(None, description="Общий объём RAM в мегабайтах", example=3867.6)
    memory_percent: float | None = Field(None, description="Процент использования RAM", example=55.8)
    disk_used_gb: float = Field(0.0, description="Использование диска в гигабайтах", example=0.0)
    disk_total_gb: float = Field(0.0, description="Общий объём диска в гигабайтах", example=0.06)
    disk_percent: float = Field(0.0, description="Процент использования диска", example=0.0)


class CpuMetrics(BaseModel):
    """Агрегированные метрики CPU по системным контейнерам."""
    percent: float = Field(..., description="Суммарный процент CPU всех системных контейнеров", example=2.3)
    containers_count: int = Field(..., description="Количество системных контейнеров", example=4)


class MemoryMetrics(BaseModel):
    """Агрегированные метрики памяти по системным контейнерам."""
    used_bytes: int = Field(..., description="Суммарное использование RAM в байтах", example=180117504)
    limit_bytes: int = Field(..., description="Суммарный лимит RAM в байтах", example=16222027776)
    used_mb: float = Field(..., description="Суммарное использование RAM в мегабайтах", example=171.8)
    limit_mb: float | None = Field(None, description="Суммарный лимит RAM в мегабайтах", example=15470.5)
    percent: float | None = Field(None, description="Суммарный процент использования RAM", example=1.1)


class ContainerMetrics(BaseModel):
    """Метрики одного системного контейнера (CPU/RAM)."""
    id: str = Field(..., description="Короткий ID контейнера", example="docker-055c3")
    name: str = Field(..., description="Имя контейнера", example="wifiaudit-tool-manager")
    cpu_percent: float | None = Field(None, description="Процент использования CPU", example=0.1)
    memory_used_bytes: int = Field(0, description="Использование RAM в байтах", example=55857152)
    memory_limit_bytes: int | None = Field(None, description="Лимит RAM в байтах (из docker-compose)", example=268435456)
    memory_used_mb: float = Field(0.0, description="Использование RAM в мегабайтах", example=53.3)
    memory_limit_mb: float | None = Field(None, description="Лимит RAM в мегабайтах", example=256.0)
    memory_percent: float | None = Field(None, description="Процент использования RAM", example=20.8)


class DiskMetrics(BaseModel):
    """Метрики диска (файловая система)."""
    used_gb: float = Field(..., description="Использование диска в гигабайтах", example=0.0)
    total_gb: float = Field(..., description="Общий объём диска в гигабайтах", example=0.06)
    percent: float = Field(..., description="Процент использования диска", example=0.0)
    path: str = Field(..., description="Путь к файловой системе", example="/")


class SystemMetrics(BaseModel):
    """Системные метрики: хост + системные контейнеры."""
    host: HostMetrics = Field(..., description="Метрики хостовой системы")
    cpu: CpuMetrics = Field(..., description="Агрегированные метрики CPU контейнеров")
    memory: MemoryMetrics = Field(..., description="Агрегированные метрики памяти контейнеров")
    containers: list[ContainerMetrics] = Field(default_factory=list, description="Метрики по каждому системному контейнеру")
    disk: DiskMetrics = Field(..., description="Метрики диска")
    source_ok: bool = Field(True, description="Удалось ли собрать метрики без ошибок интеграции")
    errors: list[str] = Field(default_factory=list, description="Список ошибок интеграции cAdvisor (если есть)")
