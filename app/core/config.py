from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Sklad Service"
    deployment_mode: Literal["demo", "staging", "production"] = "demo"
    database_backend: Literal["sqlite", "postgresql"] = "sqlite"
    database_url: str = "sqlite:///./sklad.db"
    public_access_enabled: bool = True
    dev_auth_enabled: bool = False
    jwt_hmac_secret: str | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_clock_skew_seconds: int = 30
    background_jobs_enabled: bool = False
    background_jobs_interval_seconds: int = 3600
    background_jobs_expiry_days: int = 30
    background_jobs_actor_id: str = "system-scheduler"
    telegram_bot_token: str = "8926232449:AAGAGxc9l6QZrASciAT4mqK0gF3l4cU_M-I"
    telegram_upload_chat_id: str = "-1003931832177"

    model_config = SettingsConfigDict(env_prefix="SKLAD_", env_file=".env")

    def database_url_matches_backend(self) -> bool:
        if self.database_backend == "sqlite":
            return self.database_url.startswith("sqlite:///")
        return self.database_url.startswith(("postgresql://", "postgresql+psycopg://"))

    def database_backend_allowed_for_mode(self) -> bool:
        return self.deployment_mode == "demo" or self.database_backend == "postgresql"

    def runtime_configuration_error(self) -> str | None:
        if not self.database_url_matches_backend():
            return "SKLAD_DATABASE_BACKEND does not match SKLAD_DATABASE_URL"
        if not self.database_backend_allowed_for_mode():
            return "SQLite is allowed only in SKLAD_DEPLOYMENT_MODE=demo"
        if self.deployment_mode == "production" and self.dev_auth_enabled:
            return "SKLAD_DEV_AUTH_ENABLED must be false in production"
        return None

    @property
    def sqlite_path(self) -> str:
        if self.database_backend != "sqlite":
            raise ValueError("SQLite path is only available for sqlite:/// database URLs")
        if not self.database_url_matches_backend():
            raise ValueError("SQLite backend requires sqlite:/// database URL")
        return self.database_url.removeprefix("sqlite:///")


@lru_cache
def get_settings() -> Settings:
    return Settings()
