import pytest
from pydantic import ValidationError

from app.model_routing import ResponseMode
from app.schemas.chat import CreateMessageRequest


def test_response_mode_defaults_to_auto_for_existing_clients() -> None:
    request = CreateMessageRequest.model_validate({"content": "What was revenue?"})

    assert request.response_mode is ResponseMode.AUTO


@pytest.mark.parametrize("mode", list(ResponseMode))
def test_only_strict_response_mode_enum_values_are_accepted(mode: ResponseMode) -> None:
    request = CreateMessageRequest.model_validate(
        {"content": "What was revenue?", "response_mode": mode.value}
    )

    assert request.response_mode is mode


@pytest.mark.parametrize(
    "forged_field",
    [
        {"model": "google/gemini-3.7-flash"},
        {"provider": "google-vertex"},
        {"route_reason": "SIMPLE_LOW_RISK"},
        {"reasoning_effort": "high"},
        {"tenant_id": "forged"},
        {"company": "forged"},
        {"department": "LEGAL"},
        {"role": "admin"},
        {"user_id": "forged"},
        {"allow_fallbacks": True},
        {"max_tokens": 999999},
    ],
)
def test_model_provider_routing_and_scope_overrides_are_rejected(
    forged_field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CreateMessageRequest.model_validate({"content": "What was revenue?", **forged_field})


@pytest.mark.parametrize("mode", ["FAST", "slow", "gemini", "", 1, None])
def test_unknown_or_non_string_modes_are_rejected(mode: object) -> None:
    with pytest.raises(ValidationError):
        CreateMessageRequest.model_validate({"content": "What was revenue?", "response_mode": mode})
