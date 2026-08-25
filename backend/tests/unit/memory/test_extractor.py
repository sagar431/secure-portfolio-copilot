from uuid import uuid4

import pytest

from app.memory.contracts import MemoryExtractionRequest
from app.memory.extractor import DeterministicFirstMemoryCandidateExtractor


class _UnavailableSemanticExtractor:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, request: MemoryExtractionRequest):  # type: ignore[no-untyped-def]
        del request
        self.calls += 1
        raise RuntimeError("semantic provider unavailable")


def _request(text: str) -> MemoryExtractionRequest:
    return MemoryExtractionRequest(
        user_text=text,
        assistant_text="Preference acknowledged.",
        conversation_id=uuid4(),
        source_message_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_explicit_financial_format_does_not_depend_on_semantic_provider() -> None:
    semantic = _UnavailableSemanticExtractor()
    extractor = DeterministicFirstMemoryCandidateExtractor(semantic)

    candidates = await extractor.extract(
        _request("Remember that I prefer financial values in INR crores.")
    )

    assert len(candidates) == 1
    assert candidates[0].normalized_key == "financial_value_format"
    assert candidates[0].content == "Present financial values in INR crores."
    assert candidates[0].explicit is True
    assert semantic.calls == 0
