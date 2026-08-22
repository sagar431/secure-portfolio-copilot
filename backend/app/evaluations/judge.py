from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from app.core.config import Settings
from app.evaluations.contracts import StrictModel
from app.openrouter_vertex import (
    OPENROUTER_HEAVY_MODEL,
    OpenRouterProviderError,
    OpenRouterVertexClient,
    json_contract_instruction,
)


class JudgeInput(StrictModel):
    answer: Annotated[str, Field(min_length=1, max_length=2000)]
    authorized_evidence: Annotated[tuple[str, ...], Field(min_length=1, max_length=5)]


class JudgeOutput(StrictModel):
    faithfulness_score: Annotated[float, Field(ge=0.0, le=1.0)]
    citation_support_score: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: Annotated[
        tuple[
            Literal[
                "SUPPORTED",
                "PARTIAL_SUPPORT",
                "UNSUPPORTED",
                "CITATION_MISMATCH",
            ],
            ...,
        ],
        Field(min_length=1, max_length=3),
    ]


class AdvisoryJudgeResult(StrictModel):
    label: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    output: JudgeOutput
    model_name: Literal["google/gemini-3.7-flash"] = "google/gemini-3.7-flash"
    provider: Literal["google-vertex"] = "google-vertex"
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    generation_id: str | None


SYSTEM = (
    "You are an advisory faithfulness scorer. Use only the supplied authorized evidence. "
    "Return exactly one JSON object with the two numeric scores and one to three reason_codes. "
    "Allowed reason codes are SUPPORTED, PARTIAL_SUPPORT, UNSUPPORTED, and CITATION_MISMATCH. "
    "Do not use Markdown, add fields, provide explanations, or reveal reasoning."
)


class OptionalFaithfulnessJudge:
    def __init__(self, client: OpenRouterVertexClient, *, maximum_calls: int) -> None:
        if maximum_calls not in {1, 2}:
            raise ValueError("Judge call limit must be one or two")
        if client.model_name != OPENROUTER_HEAVY_MODEL or client.provider != "google-vertex":
            raise ValueError("Judge route is not approved")
        self._client = client
        self._remaining = maximum_calls

    @property
    def has_capacity(self) -> bool:
        return self._remaining > 0

    async def judge(self, item: JudgeInput) -> AdvisoryJudgeResult:
        if self._remaining <= 0:
            raise RuntimeError("Judge call limit reached")
        self._remaining -= 1
        parsed: JudgeOutput | None = None

        def validate(content: str) -> None:
            nonlocal parsed
            try:
                parsed = JudgeOutput.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise ValueError("Invalid advisory judge response") from None

        prompt = json.dumps(item.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"))
        try:
            completion = await self._client.complete(
                system_instruction=json_contract_instruction(
                    SYSTEM, JudgeOutput.model_json_schema(mode="validation")
                ),
                prompt=prompt,
                content_validator=validate,
                max_attempts=1,
            )
        except (OpenRouterProviderError, ValueError):
            raise RuntimeError("Advisory judge failed safely") from None
        if parsed is None:
            raise RuntimeError("Advisory judge failed safely")
        return AdvisoryJudgeResult(
            output=parsed,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            latency_ms=completion.latency_ms,
            generation_id=completion.generation_id,
        )


def create_optional_judge(settings: Settings, *, maximum_calls: int) -> OptionalFaithfulnessJudge:
    if settings.openrouter_api_key is None:
        raise RuntimeError("Advisory judge is unavailable")
    return OptionalFaithfulnessJudge(
        OpenRouterVertexClient(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            provider=settings.openrouter_provider,
            model_name=OPENROUTER_HEAVY_MODEL,
            timeout_seconds=min(settings.openrouter_heavy_timeout_seconds, 30.0),
            max_output_tokens=256,
        ),
        maximum_calls=maximum_calls,
    )
