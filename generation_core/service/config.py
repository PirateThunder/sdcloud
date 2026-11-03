from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERV_", extra="ignore")

    environment: str = "local"
    port: int = 58312
    api_key: str | None = None
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:52096/sdcloud_generation"
    redis_url: str = "redis://localhost:54877/0"
    job_timeout: int = 600
    simulation_timeout: int = 60
    import_timeout: int = 60
    stale_grace_seconds: int = 30
    watchdog_interval: int = 30
    jobs_root: Path = ROOT / "work_api"
    worker_concurrency: int = 2
    job_memory_mb: int = 1024
    job_max_file_mb: int = 64
    job_max_files: int = 128


@lru_cache
def get_settings() -> Settings:
    return Settings()
