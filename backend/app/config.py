"""Application settings (pydantic-settings). All values overridable via environment or .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Cloud Modernization Agent"
    version: str = "1.0.0"

    # Database: SQLite by default; PostgreSQL via postgresql+psycopg://...
    database_url: str = "sqlite:///./data/cloud_modernization.db"

    # LLM provider: "mock" (deterministic, facts-only) | "openai-compatible"
    llm_mode: str = "mock"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""  # never logged
    llm_model: str = "mock-model"

    # CORS: comma-separated origins
    cors_origins: str = "http://localhost:8015,http://127.0.0.1:8015"

    log_level: str = "INFO"

    # Estate simulator size (planted showcase apps are always included on top of the pool)
    estate_size: int = 120

    # Provider-neutral target architecture rendering profile
    default_provider_profile: str = "aws"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_mock(self) -> bool:
        return self.llm_mode.strip().lower() == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
