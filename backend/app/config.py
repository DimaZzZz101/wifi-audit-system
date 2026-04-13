"""Application configuration."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEYS = {
    "",
    "change-me-in-production-use-openssl-rand-hex-32",
}
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "WiFi Audit"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://wifiaudit:wifiaudit@db:5432/wifiaudit"

    # Auth
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    # Метрики: cAdvisor (хост + контейнеры).
    cadvisor_url: str = "http://cadvisor:8080"
    # Точные имена системных контейнеров (fallback, если labels в cAdvisor недоступны).
    system_container_names: list[str] = [
        "wifiaudit-db",
        "wifiaudit-api",
        "wifiaudit-frontend",
        "wifiaudit-tool-manager",
    ]

    # Plugins: каталог манифестов (JSON). В Docker - монтировать volume и задать PLUGINS_DIR=/app/plugins
    plugins_dir: str = ""

    # Модули: URL каталога доступных модулей (JSON). Пусто = только установленные.
    modules_index_url: str = ""
    # Базовый URL для скачивания пакетов, если в каталоге указаны относительные пути (опционально).
    modules_download_base_url: str = ""

    # TOOL-manager: URL сервиса управления контейнерами (системная плоскость). Gateway проксирует запросы с JWT.
    tool_manager_url: str = "http://tool-manager:8001"
    # Каталог системного хранилища артефактов (pcap, handshakes и т.д.).
    artifacts_dir: str = "/data/artifacts"
    # Хостовый путь к артефактам (для volume mounts в tool-контейнерах через docker.sock).
    artifacts_host_path: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    secret = (settings.secret_key or "").strip()
    if secret in INSECURE_SECRET_KEYS or len(secret) < MIN_SECRET_KEY_LENGTH:
        raise ValueError(
            "Unsafe SECRET_KEY: set a strong key (at least 32 chars) via environment variable."
        )
    return settings
