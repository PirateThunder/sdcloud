"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "sdCloud"
    app_version: str = "1.0.2"
    debug: bool = False
    environment: str = "development"

    # Server (random high-range port to avoid conflicts with other projects)
    host: str = "0.0.0.0"
    port: int = 54101

    # Database (local development defaults, random high-range ports)
    database_url: str = "postgresql+asyncpg://sdcloud:sdcloud@localhost:50728/sdcloud"

    # Redis (local development defaults, DB index 1 to isolate from other projects)
    redis_url: str = "redis://localhost:54507/1"

    # Security
    secret_key: str = "super-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    frontend_url: str = "http://localhost:56555"
    cors_origins: str = "http://localhost:56555,http://localhost:5173"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/google/gemma-4-31b-it:free"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def async_database_url(self) -> str:
        """Ensure the database URL uses the asyncpg driver."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif not url.startswith("postgresql+asyncpg://"):
            url = url.replace("://", "+asyncpg://", 1) if "://" in url else f"postgresql+asyncpg://{url}"
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
