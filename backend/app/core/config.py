from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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
    embedding_provider: Literal["ollama", "fake", "disabled"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    embedding_model_name: str = "nomic-embed-text"
    embedding_model_version: str = "v1.5"
    embedding_dimensions: int = Field(default=768, ge=1, le=4096)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    embedding_max_chunks: int = Field(default=512, ge=1, le=2048)
    embedding_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    embedding_operation_timeout_seconds: float = Field(default=120.0, ge=1.0, le=300.0)
    cors_origins: list[str] = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]

    @model_validator(mode="after")
    def reject_development_jwt_key_in_production(self) -> "Settings":
        if self.embedding_model_name != "nomic-embed-text":
            raise ValueError("EMBEDDING_MODEL_NAME must be nomic-embed-text")
        if self.embedding_model_version != "v1.5":
            raise ValueError("EMBEDDING_MODEL_VERSION must be v1.5")
        if self.embedding_dimensions != 768:
            raise ValueError("EMBEDDING_DIMENSIONS must be 768")
        if self.app_env == "production" and self.embedding_provider != "disabled":
            raise ValueError("Development embedding providers are unavailable in production")
        parsed_ollama = urlsplit(self.ollama_base_url)
        hostname = parsed_ollama.hostname
        is_loopback = hostname == "localhost"
        if hostname and hostname != "localhost":
            try:
                is_loopback = ip_address(hostname).is_loopback
            except ValueError:
                is_loopback = False
        if (
            parsed_ollama.scheme != "http"
            or not is_loopback
            or parsed_ollama.username is not None
            or parsed_ollama.password is not None
            or parsed_ollama.query
            or parsed_ollama.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must identify a local development service")
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
