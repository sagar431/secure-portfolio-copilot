import json

import pytest

from app.evaluations.judge import JudgeInput, OptionalFaithfulnessJudge
from app.openrouter_vertex import OpenRouterCompletion


class FakeClient:
    model_name = "google/gemini-3.7-flash"
    provider = "google-vertex"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def complete(self, **kwargs: object) -> OpenRouterCompletion:
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        validator = kwargs["content_validator"]
        validator(content)  # type: ignore[operator]
        return OpenRouterCompletion(content, "safe", "stop", 12, 6, 4, 0)


@pytest.mark.asyncio
async def test_judge_is_strict_advisory_and_bounded_to_two_total_calls() -> None:
    valid = json.dumps(
        {
            "faithfulness_score": 1.0,
            "citation_support_score": 0.95,
            "reason_codes": ["SUPPORTED"],
        }
    )
    client = FakeClient([valid, valid, valid])
    judge = OptionalFaithfulnessJudge(client, maximum_calls=2)  # type: ignore[arg-type]
    item = JudgeInput(answer="Controlled answer", authorized_evidence=("Authorized evidence",))

    first = await judge.judge(item)
    second = await judge.judge(item)
    with pytest.raises(RuntimeError, match="limit"):
        await judge.judge(item)

    assert first.label == second.label == "ADVISORY_ONLY"
    assert len(client.calls) == 2
    assert all(call["max_attempts"] == 1 for call in client.calls)
    assert all("Authorized evidence" in str(call["prompt"]) for call in client.calls)


@pytest.mark.asyncio
async def test_judge_rejects_extra_fields_without_exposing_body() -> None:
    client = FakeClient(
        [
            '{"faithfulness_score":1,"citation_support_score":1,"reason_codes":[],"reasoning":"secret"}'
        ]
    )
    judge = OptionalFaithfulnessJudge(client, maximum_calls=1)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="failed safely") as raised:
        await judge.judge(
            JudgeInput(answer="Controlled answer", authorized_evidence=("Authorized evidence",))
        )

    assert "secret" not in str(raised.value)
