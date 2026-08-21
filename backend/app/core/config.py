from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ollama_qwen import QWEN_BASE_URL, QWEN_MODEL
from app.runpod_kimi import (
    RUNPOD_KIMI_BASE_URL,
    RUNPOD_KIMI_MIN_OUTPUT_TOKENS,
    RUNPOD_KIMI_MODEL,
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
    llm_provider: Literal["router", "gemini", "runpod", "fake", "disabled"] = "gemini"
    gemini_api_key: SecretStr | None = None
    llm_model_name: str = "gemini-3.7-flash"
    llm_thinking_level: str = "medium"
    runpod_api_key: SecretStr | None = None
    runpod_base_url: str = RUNPOD_KIMI_BASE_URL
    runpod_model_name: str = RUNPOD_KIMI_MODEL
    qwen_base_url: str = QWEN_BASE_URL
    qwen_model_name: str = QWEN_MODEL
    qwen_timeout_seconds: float = Field(default=15.0, ge=1.0, le=30.0)
    qwen_max_output_tokens: int = Field(default=1024, ge=256, le=2048)
    router_low_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    llm_timeout_seconds: float = Field(default=30.0, ge=1.0, le=60.0)
    llm_max_output_tokens: int = Field(default=1024, ge=256, le=2048)
    llm_max_evidence_chunks: int = Field(default=5, ge=1, le=10)
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
        if self.llm_provider == "gemini":
            if self.llm_model_name != "gemini-3.7-flash":
                raise ValueError("LLM_MODEL_NAME must be gemini-3.7-flash")
            if self.llm_thinking_level != "medium":
                raise ValueError("LLM_THINKING_LEVEL must be medium")
        if self.llm_provider in {"runpod", "router"}:
            if self.runpod_base_url != RUNPOD_KIMI_BASE_URL:
                raise ValueError("RUNPOD_BASE_URL must be the approved Kimi endpoint")
            if self.runpod_model_name != RUNPOD_KIMI_MODEL:
                raise ValueError("RUNPOD_MODEL_NAME must be kimi-k3")
            if self.llm_max_output_tokens < RUNPOD_KIMI_MIN_OUTPUT_TOKENS:
                raise ValueError("Runpod Kimi requires at least 1024 output tokens")
        if self.llm_provider == "router":
            if self.qwen_base_url != QWEN_BASE_URL:
                raise ValueError("QWEN_BASE_URL must be the approved Mac Ollama endpoint")
            if self.qwen_model_name != QWEN_MODEL:
                raise ValueError("QWEN_MODEL_NAME must be qwen3:8b")
            if self.app_env == "production":
                raise ValueError("The LAN model router is unavailable in production")
        if self.app_env == "production" and self.embedding_provider != "disabled":
            raise ValueError("Development embedding providers are unavailable in production")
        if self.app_env == "production" and self.llm_provider == "fake":
            raise ValueError("The fake LLM provider is unavailable in production")
        if (
            self.app_env == "production"
            and self.llm_provider == "gemini"
            and self.gemini_api_key is None
        ):
            raise ValueError("GEMINI_API_KEY must be configured for the Gemini provider")
        if (
            self.app_env == "production"
            and self.llm_provider in {"runpod", "router"}
            and self.runpod_api_key is None
        ):
            raise ValueError("RUNPOD_API_KEY must be configured for the Runpod provider")
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
