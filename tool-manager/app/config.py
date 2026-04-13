"""TOOL-manager config. SECRET_KEY и algorithm должны совпадать с API-Gateway для проверки JWT."""
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

    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    algorithm: str = "HS256"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    secret = (settings.secret_key or "").strip()
    if secret in INSECURE_SECRET_KEYS or len(secret) < MIN_SECRET_KEY_LENGTH:
        raise ValueError(
            "Unsafe SECRET_KEY: set a strong key (at least 32 chars) via environment variable."
        )
    return settings
