"""Live, content-free Runpod Kimi contract smoke.

This script intentionally prints only bounded contract metadata. It never prints
credentials, prompts, evidence, answers, provider bodies, or reasoning content.
"""

import asyncio
from uuid import uuid4

from app.agent.contracts import AgentModelError
from app.agent.factory import create_agent_stage_providers
from app.agent.models import (
    ActionType,
    ObservationStatus,
    RemainingBudgets,
    StructuredObservation,
)
from app.agent.plan_state import PlanState
from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest, LLMProviderError
from app.chat.factory import create_llm_provider
from app.chat.service import validate_grounded_answer
from app.core.config import Settings
from app.mcp_gateway.contracts import (
    ApprovedToolName,
    PermittedToolDescriptor,
    PermittedToolInputField,
    PermittedToolInputSchema,
)


def _search_descriptor() -> PermittedToolDescriptor:
    return PermittedToolDescriptor(
        name=ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        purpose="Search authorized portfolio documents for evidence relevant to one bounded query.",
        input_schema=PermittedToolInputSchema(
            fields=(
                PermittedToolInputField(
                    name="query",
                    value_type="string",
                    required=True,
                    min_length=1,
                    max_length=500,
                ),
                PermittedToolInputField(
                    name="top_k",
                    value_type="integer",
                    required=True,
                    minimum=1,
                    maximum=20,
                ),
            )
        ),
        safe_result_description="Authorized evidence excerpts with host-owned provenance.",
    )


async def main() -> None:
    settings = Settings()
    if settings.llm_provider != "runpod":
        raise RuntimeError("Set LLM_PROVIDER=runpod before running this live smoke")

    perception_provider, decision_provider = create_agent_stage_providers(settings)
    finalizer = create_llm_provider(settings)
    query = "What value does the synthetic authorized financial evidence report?"

    perception = await perception_provider.perceive_user_query(query=query)
    decision = await decision_provider.decide_initial(
        query=query,
        perception=perception,
        permitted_tool_catalog=(_search_descriptor(),),
    )
    if decision.next_action.action_name != ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS:
        raise RuntimeError("Live Decision did not select the sole permitted search tool")

    evidence = (
        GroundedEvidence(
            evidence_id="ev_1",
            chunk_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            version_number=1,
            document_title="synthetic.pdf",
            excerpt="The synthetic authorized financial value is 125.",
            page_number=1,
            sheet_name=None,
            row_start=None,
            row_end=None,
            cell_start=None,
            cell_end=None,
        ),
    )
    plan_state = PlanState.initial(decision).complete_next(decision.next_action)
    step_perception = await perception_provider.perceive_step_result(
        query=query,
        previous=perception,
        current_plan=plan_state.current_plan,
        completed_steps=plan_state.completed_history,
        observation=StructuredObservation(
            tool_name=ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
            status=ObservationStatus.SUCCESS,
            evidence=evidence,
            duration_ms=1,
            reason_code="TOOL_COMPLETED",
        ),
        remaining_budgets=RemainingBudgets(
            tool_steps=3,
            retrieval_rewrites=1,
            replans=1,
            latest_tool_retries=0,
            duration_ms=1,
        ),
    )
    final_decision = await decision_provider.decide_mid_session(
        query=query,
        perception=step_perception,
        current_plan=plan_state.current_plan,
        completed_steps=plan_state.completed_history,
        permitted_tool_catalog=(_search_descriptor(),),
    )
    if final_decision.next_action.type != ActionType.FINALIZE:
        raise RuntimeError("Live mid-session Decision did not finalize sufficient evidence")
    generation = await finalizer.generate(
        GroundedGenerationRequest(question=query, evidence=evidence)
    )
    validated = validate_grounded_answer(generation.answer, evidence)

    print("provider=runpod")
    print(f"model={perception_provider.model_name}")
    print("perception_valid=true")
    print(f"perception_mode={perception.mode.value}")
    print(f"perception_intent={perception.intent.value}")
    print("decision_valid=true")
    print(f"decision_action={decision.next_action.action_name}")
    print(f"decision_plan_steps={len(decision.plan.steps)}")
    print("step_perception_valid=true")
    print(f"step_evidence_status={step_perception.evidence_status.value}")
    print("mid_session_decision_valid=true")
    print(f"mid_session_action={final_decision.next_action.type.value}")
    print(f"final_status={generation.answer.status}")
    print(f"final_claim_count={len(validated.claims)}")
    print(
        "final_claims_cited="
        + str(
            bool(validated.claims)
            and all(
                claim.citation_ids and set(claim.citation_ids) <= {"ev_1"}
                for claim in validated.claims
            )
        ).lower()
    )
    print(f"final_retry_count={generation.usage.retry_count}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AgentModelError as exc:
        print(f"live_agent_error={exc.code.value}")
        raise SystemExit(1) from None
    except LLMProviderError as exc:
        print(f"live_finalizer_error={exc.code.value}")
        raise SystemExit(1) from None
