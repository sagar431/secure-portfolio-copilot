import pytest
from pydantic import SecretStr, ValidationError

from app.agent.factory import agent_route_reason, create_agent_stage_providers
from app.agent.runpod import RunpodKimiDecisionProvider, RunpodKimiPerceptionProvider
from app.chat.factory import create_agent_finalizer, create_llm_provider
from app.chat.router import DeterministicRoutingLLMProvider
from app.chat.runpod import RunpodKimiLLMProvider
from app.core.config import Settings


def _router_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "llm_provider": "router",
        "runpod_api_key": SecretStr("synthetic"),
        "llm_max_output_tokens": 1024,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_router_settings_pin_both_endpoints_and_models() -> None:
    settings = _router_settings()
    assert settings.qwen_base_url == "http://192.168.31.213:11434"
    assert settings.qwen_model_name == "qwen3:8b"
    assert settings.runpod_model_name == "kimi-k3"

    with pytest.raises(ValidationError, match="approved Mac Ollama endpoint"):
        _router_settings(qwen_base_url="http://attacker.invalid:11434")
    with pytest.raises(ValidationError, match="qwen3:8b"):
        _router_settings(qwen_model_name="other")
    with pytest.raises(ValidationError, match="unavailable in production"):
        _router_settings(app_env="production", embedding_provider="disabled")


def test_router_factory_routes_only_grounded_simple_work_to_qwen() -> None:
    settings = _router_settings()

    grounded = create_llm_provider(settings)
    perception, decision = create_agent_stage_providers(settings)
    finalizer = create_agent_finalizer(settings)

    assert isinstance(grounded, DeterministicRoutingLLMProvider)
    assert isinstance(perception, RunpodKimiPerceptionProvider)
    assert isinstance(decision, RunpodKimiDecisionProvider)
    assert isinstance(finalizer, RunpodKimiLLMProvider)
    assert agent_route_reason(settings) == "AGENTIC_REQUEST"
