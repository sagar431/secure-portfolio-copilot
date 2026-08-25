from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.openrouter_vertex import (
    OPENROUTER_BASE_URL,
    OPENROUTER_HEAVY_MODEL,
    OPENROUTER_PROVIDER,
    OPENROUTER_SIMPLE_MODEL,
)


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
    llm_provider: Literal["openrouter_vertex", "fake", "disabled"] = "openrouter_vertex"
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = OPENROUTER_BASE_URL
    openrouter_provider: str = OPENROUTER_PROVIDER
    openrouter_simple_model: str = OPENROUTER_SIMPLE_MODEL
    openrouter_heavy_model: str = OPENROUTER_HEAVY_MODEL
    openrouter_simple_timeout_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    openrouter_heavy_timeout_seconds: float = Field(default=60.0, ge=1.0, le=120.0)
    openrouter_simple_max_output_tokens: int = Field(default=1024, ge=256, le=2048)
    openrouter_heavy_max_output_tokens: int = Field(default=1536, ge=256, le=2048)
    router_low_confidence_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    llm_max_evidence_chunks: int = Field(default=5, ge=1, le=10)
    memory_recent_message_limit: int = Field(default=8, ge=2, le=20)
    memory_max_items: int = Field(default=5, ge=0, le=10)
    memory_context_char_budget: int = Field(default=2400, ge=500, le=6000)
    memory_semantic_expiry_days: int = Field(default=90, ge=1, le=365)
    memory_episodic_expiry_days: int = Field(default=30, ge=1, le=180)
    agent_max_steps: int = Field(default=4, ge=1, le=4)
    agent_max_replans: int = Field(default=1, ge=0, le=1)
    agent_max_retrieval_rewrites: int = Field(default=1, ge=0, le=1)
    agent_max_duration_seconds: float = Field(default=90.0, ge=5.0, le=120.0)
    agent_tool_timeout_seconds: float = Field(default=10.0, ge=0.1, le=30.0)
    agent_tool_max_transient_retries: int = Field(default=1, ge=0, le=1)
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
        if self.openrouter_base_url != OPENROUTER_BASE_URL:
            raise ValueError("OPENROUTER_BASE_URL must be the approved OpenRouter endpoint")
        if self.openrouter_provider != OPENROUTER_PROVIDER:
            raise ValueError("OPENROUTER_PROVIDER must be google-vertex")
        if self.openrouter_simple_model != OPENROUTER_SIMPLE_MODEL:
            raise ValueError("OPENROUTER_SIMPLE_MODEL must be google/gemini-3.1-flash-lite")
        if self.openrouter_heavy_model != OPENROUTER_HEAVY_MODEL:
            raise ValueError("OPENROUTER_HEAVY_MODEL must be google/gemini-3.7-flash")
        if self.app_env == "production" and self.embedding_provider != "disabled":
            raise ValueError("Development embedding providers are unavailable in production")
        if self.app_env == "production" and self.llm_provider == "fake":
            raise ValueError("The fake LLM provider is unavailable in production")
        if (
            self.app_env == "production"
            and self.llm_provider == "openrouter_vertex"
            and self.openrouter_api_key is None
        ):
            raise ValueError("OPENROUTER_API_KEY must be configured for OpenRouter Vertex")
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
