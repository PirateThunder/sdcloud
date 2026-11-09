from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BACK_")

    env: str = "local"
    port: int = 61230
    database_url: str = "postgresql+asyncpg://back:back@localhost:5432/back"
    redis_url: str = "redis://localhost:6379/0"
    generator_url: str = "http://localhost:50457"
    generator_api_key: str | None = None
    cors_origins: str = "http://localhost:3000,http://localhost:56555"
    trust_proxy_headers: bool = False

    jwt_secret: str = "sdcloud-local-jwt-secret-change-me"
    otp_secret: str = "sdcloud-local-otp-secret-change-me"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    refresh_cookie: str = "sdcloud_refresh"

    email_code_ttl_seconds: int = 600
    email_code_cooldown_seconds: int = 60
    email_code_max_attempts: int = 5
    email_code_daily_per_email: int = 10
    email_code_daily_per_ip: int = 30
    email_code_verify_per_ip: int = 30
    email_dev_code: bool = False
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_timeout_seconds: int = 15

    generation_timeout_seconds: int = 600
    simulation_timeout_seconds: int = 120
    core_submit_timeout_seconds: int = 60
    poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 30
    queued_retry_after_seconds: int = 5
    watchdog_interval_seconds: int = 5
    generation_per_hour: int = 30
    simulation_per_hour: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.env not in {"local", "test"}:
            if self.jwt_secret.startswith("sdcloud-local-") or self.otp_secret.startswith(
                "sdcloud-local-"
            ):
                raise ValueError("BACK_JWT_SECRET and BACK_OTP_SECRET are required outside local")
            if self.email_dev_code:
                raise ValueError("BACK_EMAIL_DEV_CODE is allowed only in local/test")
            if not self.smtp_host:
                raise ValueError("BACK_SMTP_HOST is required outside local/test")
            if not (self.smtp_from or self.smtp_user):
                raise ValueError("BACK_SMTP_FROM or BACK_SMTP_USER is required outside local/test")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
