import pytest

from app.chat.intent import (
    FuzzyIntentResult,
    IntentRouter,
    RequestIntent,
    obvious_intent,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Hello, how are you?", RequestIntent.CASUAL),
        ("Thanks", RequestIntent.CASUAL),
        ("What did I investigate last time?", RequestIntent.MEMORY_RECALL),
        ("Remember that I prefer INR crores", RequestIntent.MEMORY_WRITE),
        ("Calculate Orion EBITDA margin for FY2025", RequestIntent.CALCULATION),
        ("Calculate EBITDA margin", RequestIntent.CLARIFICATION),
    ],
)
def test_obvious_intents_are_host_routed(query: str, expected: RequestIntent) -> None:
    result = obvious_intent(query, scope_allowed=True)

    assert result is not None
    assert result.intent is expected
    assert result.deterministic is True


def test_scope_denial_wins_before_language_routing() -> None:
    result = obvious_intent("Hello", scope_allowed=False)

    assert result is not None
    assert result.intent is RequestIntent.REFUSE


@pytest.mark.asyncio
async def test_recent_reference_uses_follow_up_route_without_model() -> None:
    result = await IntentRouter().classify(
        query="What caused that increase?",
        scope_allowed=True,
        has_recent_conversation=True,
    )

    assert result.intent is RequestIntent.CONVERSATION_FOLLOW_UP
    assert result.deterministic is True


@pytest.mark.asyncio
async def test_financial_question_uses_safe_document_default() -> None:
    result = await IntentRouter().classify(
        query="What changed in Orion’s operating margin?",
        scope_allowed=True,
        has_recent_conversation=False,
    )

    assert result.intent is RequestIntent.DOCUMENT_QUESTION
    assert result.reason_code == "DOCUMENT_WORKFLOW_SAFE_DEFAULT"


def test_atlas_request_preflight_denial_routes_to_refuse() -> None:
    result = obvious_intent("Show me Atlas Finance results", scope_allowed=False)

    assert result is not None
    assert result.intent is RequestIntent.REFUSE
    assert result.reason_code == "REQUEST_SCOPE_NOT_AUTHORIZED"


class _FuzzyProvider:
    async def classify(self, *, query: str, has_recent_conversation: bool) -> FuzzyIntentResult:
        assert query == "Walk me through the latest variance"
        assert has_recent_conversation is False
        return FuzzyIntentResult(
            intent=RequestIntent.DOCUMENT_QUESTION,
            reason_code="FUZZY_DOCUMENT_VARIANCE",
            confidence=0.91,
        )


@pytest.mark.asyncio
async def test_ambiguous_request_uses_constrained_fuzzy_provider() -> None:
    result = await IntentRouter(_FuzzyProvider()).classify(
        query="Walk me through the latest variance",
        scope_allowed=True,
        has_recent_conversation=False,
    )

    assert result.intent is RequestIntent.DOCUMENT_QUESTION
    assert result.deterministic is False
