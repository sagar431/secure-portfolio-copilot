"""Content-free live contract smoke for both pinned OpenRouter Vertex models."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.models import DecisionResult, PerceptionSnapshot
from app.agent.prompts import (
    DECISION_SYSTEM_INSTRUCTION,
    PERCEPTION_SYSTEM_INSTRUCTION,
    initial_decision_prompt,
    user_query_perception_prompt,
)
from app.chat.prompt import SYSTEM_INSTRUCTION
from app.chat.structured_answer import AnswerSchema
from app.core.config import get_settings
from app.openrouter_vertex import (
    OpenRouterCompletion,
    OpenRouterErrorCode,
    OpenRouterProviderError,
    OpenRouterVertexClient,
    json_contract_instruction,
)


@dataclass(frozen=True, slots=True)
class _SafeGenerationMetadata:
    provider: str
    is_byok: bool
    inference_cost: Decimal


def _strict_validator(
    model: type[BaseModel],
) -> tuple[Callable[[], BaseModel | None], Callable[[str], None]]:
    parsed: BaseModel | None = None

    def validate(content: str) -> None:
        nonlocal parsed
        try:
            parsed = model.model_validate_json(content, strict=True)
        except (TypeError, ValueError, ValidationError):
            raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None

    return lambda: parsed, validate


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise RuntimeError("INVALID_METADATA")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise RuntimeError("INVALID_METADATA") from None


async def _metadata(*, api_key: str, base_url: str, generation_id: str) -> _SafeGenerationMetadata:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30), trust_env=False) as client:
        for attempt in range(15):
            response = await client.get(
                f"{base_url}/generation",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"id": generation_id},
            )
            if response.status_code == 404 and attempt < 14:
                await asyncio.sleep(1)
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"METADATA_HTTP_{response.status_code}")
            try:
                payload = response.json()
            except (TypeError, ValueError):
                raise RuntimeError("INVALID_METADATA") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                raise RuntimeError("INVALID_METADATA")
            data = payload["data"]
            provider = data.get("provider_name")
            is_byok = data.get("is_byok")
            # OpenRouter's charge is total_cost. upstream_inference_cost is the
            # estimated underlying Vertex charge and is not an OpenRouter debit.
            inference_cost = _decimal(data.get("total_cost", 0))
            if not isinstance(provider, str) or not isinstance(is_byok, bool):
                raise RuntimeError("INVALID_METADATA")
            return _SafeGenerationMetadata(provider, is_byok, inference_cost)
    raise RuntimeError("METADATA_UNAVAILABLE")


async def _report(
    *,
    label: str,
    client: OpenRouterVertexClient,
    completion: OpenRouterCompletion,
    api_key: str,
) -> None:
    if completion.generation_id is None:
        raise RuntimeError("MISSING_GENERATION_ID")
    metadata = await _metadata(
        api_key=api_key,
        base_url=client.base_url,
        generation_id=completion.generation_id,
    )
    if metadata.provider != "Google" or not metadata.is_byok or metadata.inference_cost != 0:
        print(
            json.dumps(
                {
                    "check": label,
                    "model": client.model_name,
                    "provider": metadata.provider,
                    "is_byok": metadata.is_byok,
                    "finish_reason": completion.finish_reason,
                    "strict_validation": True,
                    "latency_ms": completion.latency_ms,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "inference_cost": str(metadata.inference_cost),
                    "safe_error_code": "BYOK_ROUTE_MISMATCH",
                },
                separators=(",", ":"),
            )
        )
        raise RuntimeError("BYOK_ROUTE_MISMATCH")
    print(
        json.dumps(
            {
                "check": label,
                "model": client.model_name,
                "provider": metadata.provider,
                "is_byok": metadata.is_byok,
                "finish_reason": completion.finish_reason,
                "strict_validation": True,
                "latency_ms": completion.latency_ms,
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "inference_cost": str(metadata.inference_cost),
                "safe_error_code": None,
            },
            separators=(",", ":"),
        )
    )


async def _run() -> None:
    settings = get_settings()
    if settings.llm_provider != "openrouter_vertex" or settings.openrouter_api_key is None:
        raise RuntimeError("OPENROUTER_VERTEX_NOT_CONFIGURED")
    api_key = settings.openrouter_api_key.get_secret_value()
    simple = OpenRouterVertexClient(
        api_key=api_key,
        base_url=settings.openrouter_base_url,
        provider=settings.openrouter_provider,
        model_name=settings.openrouter_simple_model,
        timeout_seconds=settings.openrouter_simple_timeout_seconds,
        max_output_tokens=settings.openrouter_simple_max_output_tokens,
    )
    heavy = OpenRouterVertexClient(
        api_key=api_key,
        base_url=settings.openrouter_base_url,
        provider=settings.openrouter_provider,
        model_name=settings.openrouter_heavy_model,
        timeout_seconds=settings.openrouter_heavy_timeout_seconds,
        max_output_tokens=settings.openrouter_heavy_max_output_tokens,
    )

    simple_get, simple_validate = _strict_validator(AnswerSchema)
    simple_completion = await simple.complete(
        system_instruction=json_contract_instruction(
            SYSTEM_INSTRUCTION, AnswerSchema.model_json_schema(mode="validation")
        ),
        prompt=(
            'Return {"status":"insufficient_evidence","claims":[],"limitations":[]}. '
            "This is a synthetic contract check with no document evidence."
        ),
        content_validator=simple_validate,
    )
    if simple_get() is None:
        raise RuntimeError("STRICT_VALIDATION_FAILED")
    await _report(
        label="structured_contract", client=simple, completion=simple_completion, api_key=api_key
    )

    perception_get, perception_validate = _strict_validator(PerceptionSnapshot)
    perception_completion = await heavy.complete(
        system_instruction=json_contract_instruction(
            PERCEPTION_SYSTEM_INSTRUCTION,
            PerceptionSnapshot.model_json_schema(mode="validation"),
        ),
        prompt=user_query_perception_prompt("Summarize an authorized portfolio document."),
        content_validator=perception_validate,
    )
    perception = perception_get()
    if not isinstance(perception, PerceptionSnapshot):
        raise RuntimeError("STRICT_VALIDATION_FAILED")
    await _report(
        label="perception", client=heavy, completion=perception_completion, api_key=api_key
    )

    decision_get, decision_validate = _strict_validator(DecisionResult)
    decision_completion = await heavy.complete(
        system_instruction=json_contract_instruction(
            DECISION_SYSTEM_INSTRUCTION, DecisionResult.model_json_schema(mode="validation")
        ),
        prompt=initial_decision_prompt(
            "Summarize an authorized portfolio document.", perception, ()
        ),
        content_validator=decision_validate,
    )
    if decision_get() is None:
        raise RuntimeError("STRICT_VALIDATION_FAILED")
    await _report(label="decision", client=heavy, completion=decision_completion, api_key=api_key)


def main() -> None:
    try:
        asyncio.run(_run())
    except (OpenRouterProviderError, RuntimeError, ValidationError) as exc:
        code = (
            exc.code.value
            if isinstance(exc, OpenRouterProviderError)
            else str(exc)
            if isinstance(exc, RuntimeError)
            else "STRICT_VALIDATION_FAILED"
        )
        print(json.dumps({"safe_error_code": code}, separators=(",", ":")))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
