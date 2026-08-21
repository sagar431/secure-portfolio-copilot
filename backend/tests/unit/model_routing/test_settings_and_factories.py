import pytest
from pydantic import SecretStr, ValidationError

from app.agent.factory import agent_route_reason, create_agent_stage_providers
from app.agent.openrouter_vertex import (
    OpenRouterVertexDecisionProvider,
    OpenRouterVertexPerceptionProvider,
)
from app.chat.factory import create_agent_finalizer, create_llm_provider
from app.chat.openrouter_vertex import OpenRouterVertexLLMProvider
from app.chat.router import DeterministicRoutingLLMProvider
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "llm_provider": "openrouter_vertex",
        "openrouter_api_key": SecretStr("synthetic"),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_openrouter_vertex_settings_are_exact_and_secret_typed() -> None:
    settings = _settings()
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.openrouter_provider == "google-vertex"
    assert settings.openrouter_simple_model == "google/gemini-3.1-flash-lite"
    assert settings.openrouter_heavy_model == "google/gemini-3.7-flash"
    assert isinstance(settings.openrouter_api_key, SecretStr)
    assert "synthetic" not in repr(settings)

    invalid = (
        ("openrouter_base_url", "https://attacker.invalid/v1", "approved OpenRouter endpoint"),
        ("openrouter_provider", "google", "google-vertex"),
        ("openrouter_simple_model", "arbitrary/model", "gemini-3.1-flash-lite"),
        ("openrouter_heavy_model", "arbitrary/model", "gemini-3.7-flash"),
    )
    for field, value, message in invalid:
        with pytest.raises(ValidationError, match=message):
            _settings(**{field: value})


def test_production_requires_openrouter_key() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        _settings(
            app_env="production",
            embedding_provider="disabled",
            openrouter_api_key=None,
        )


def test_factories_use_heavy_vertex_for_all_agent_stages() -> None:
    settings = _settings()

    grounded = create_llm_provider(settings)
    perception, decision = create_agent_stage_providers(settings)
    finalizer = create_agent_finalizer(settings)

    assert isinstance(grounded, DeterministicRoutingLLMProvider)
    assert isinstance(perception, OpenRouterVertexPerceptionProvider)
    assert isinstance(decision, OpenRouterVertexDecisionProvider)
    assert isinstance(finalizer, OpenRouterVertexLLMProvider)
    assert perception.model_name == "google/gemini-3.7-flash"
    assert decision.model_name == "google/gemini-3.7-flash"
    assert finalizer.model_name == "google/gemini-3.7-flash"
    assert agent_route_reason(settings) == "AGENTIC_REQUEST"
