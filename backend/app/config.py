from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, loaded from environment variables (and .env for local dev)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "VoxDesk API"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://voxdesk:voxdesk@localhost:5433/voxdesk"
    redis_url: str = "redis://localhost:6380/0"

    google_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
