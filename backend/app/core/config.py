from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Secure Portfolio Copilot API"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    backend_host: str = "127.0.0.1"
    backend_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+asyncpg://portfolio:portfolio_dev@127.0.0.1:5432/portfolio"
    jwt_secret_key: SecretStr = SecretStr("development-only-jwt-key-change-before-shared-use")
    jwt_issuer: str = "secure-portfolio-copilot"
    jwt_audience: str = "secure-portfolio-web"
    jwt_access_token_minutes: int = Field(default=15, ge=1, le=60)
    demo_user_password: SecretStr | None = None
    document_storage_path: Path = Path("../.local/document-storage")
    cors_origins: list[str] = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]

    @model_validator(mode="after")
    def reject_development_jwt_key_in_production(self) -> "Settings":
        if (
            self.app_env == "production"
            and self.jwt_secret_key.get_secret_value()
            == "development-only-jwt-key-change-before-shared-use"
        ):
            raise ValueError("JWT_SECRET_KEY must be configured in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
