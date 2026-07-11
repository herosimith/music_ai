from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MUSIC_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./.local/control-plane.db"
    object_store_root: Path = Path(".local/object-store")
    token_pepper: SecretStr = Field(min_length=32)
    raw_audio_ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    maintenance_interval_seconds: int = Field(default=300, ge=10, le=86_399)
    max_upload_bytes: int = Field(default=100_000_000, ge=1, le=100_000_000)
    deletion_retry_limit: int = Field(default=5, ge=1, le=20)
    auto_create_schema: bool = True
    bootstrap_tenant_slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]{2,63}$")
    bootstrap_tenant_name: str | None = Field(default=None, min_length=1, max_length=200)
    bootstrap_api_token: SecretStr | None = Field(default=None, min_length=32)
    coach_base_url: str | None = None
    coach_model: str | None = Field(default=None, min_length=1, max_length=200)
    coach_api_key: SecretStr | None = Field(default=None, min_length=20, max_length=2_048)
    coach_timeout_seconds: float = Field(default=10.0, ge=0.1, le=30.0)

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Settings:
        if self.maintenance_interval_seconds >= self.raw_audio_ttl_seconds:
            raise ValueError("maintenance interval must be shorter than the raw audio TTL")
        bootstrap_values = (
            self.bootstrap_tenant_slug,
            self.bootstrap_tenant_name,
            self.bootstrap_api_token,
        )
        if any(value is not None for value in bootstrap_values) and not all(
            value is not None for value in bootstrap_values
        ):
            raise ValueError("bootstrap tenant slug, name, and token must be configured together")
        coach_values = (self.coach_base_url, self.coach_model, self.coach_api_key)
        if any(value is not None for value in coach_values) and not all(
            value is not None for value in coach_values
        ):
            raise ValueError("coach base URL, model, and API key must be configured together")
        if self.environment == "production":
            if self.auto_create_schema:
                raise ValueError("production must use migrations instead of auto_create_schema")
            if self.bootstrap_api_token is not None:
                raise ValueError("production cannot bootstrap a static API token")
            if self.database_url.startswith("sqlite"):
                raise ValueError("production requires PostgreSQL")
        return self
