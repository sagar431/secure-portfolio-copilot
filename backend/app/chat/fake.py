from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedClaimDraft,
    GroundedGenerationRequest,
    LLMGeneration,
    LLMUsage,
)


class DeterministicFakeLLMProvider:
    """Deterministic fake with injectable output and observable calls for tests."""

    model_name = "fake-grounded-llm-v1"

    def __init__(self, answer: GroundedAnswerDraft | None = None) -> None:
        self.answer = answer
        self.requests: list[GroundedGenerationRequest] = []

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        self.requests.append(request)
        if self.answer is not None:
            answer = self.answer
        elif request.evidence:
            answer = GroundedAnswerDraft(
                status="supported",
                claims=(
                    GroundedClaimDraft(
                        text="The retrieved authorized evidence addresses the question.",
                        evidence_ids=(request.evidence[0].evidence_id,),
                    ),
                ),
            )
        else:
            answer = GroundedAnswerDraft(
                status="insufficient_evidence",
                claims=(),
                limitations=("No authorized evidence was retrieved.",),
            )
        return LLMGeneration(answer=answer, usage=LLMUsage(latency_ms=1))
