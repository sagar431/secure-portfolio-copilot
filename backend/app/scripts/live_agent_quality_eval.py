"""Explicit opt-in live quality checks for semantic portfolio-agent stages.

The script prints only content-free pass/fail labels. It never prints prompts, completions,
evidence text, memories, credentials, provider bodies, or model reasoning.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from uuid import uuid4

from app.agent.factory import create_agent_stage_providers
from app.agent.models import (
    ActionType,
    EvidenceStatus,
    GoalStatus,
    ObservationStatus,
    RemainingBudgets,
    StructuredObservation,
)
from app.agent.plan_state import PlanState
from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest
from app.chat.factory import (
    create_agent_finalizer,
    create_conversation_summarizer,
    create_intent_router,
    create_memory_extractor,
)
from app.chat.intent import RequestIntent
from app.core.config import get_settings
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.memory.contracts import ConversationSummaryRequest, MemoryExtractionRequest
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)


@dataclass(frozen=True, slots=True)
class _Check:
    name: str
    passed: bool


def _scope() -> AuthorizationScope:
    identity = TrustedIdentity(
        user_id=uuid4(),
        email="live-eval@example.com",
        display_name="Live Evaluation",
    )
    tenant_id = uuid4()
    return AuthorizationScope(
        identity=identity,
        grants=(
            AuthorizationGrant(
                membership_id=uuid4(),
                home_tenant_id=tenant_id,
                home_tenant_slug="orion",
                home_tenant_name="Orion Capital",
                workspace_id=tenant_id,
                workspace_slug="orion",
                workspace_name="Orion Capital",
                role="analyst",
                primary_department="finance",
                company_ids=(uuid4(),),
                company_slugs=("orion-main",),
                departments=(
                    DepartmentAccess(
                        key="finance",
                        source=GrantSource.PRIMARY_DEPARTMENT,
                    ),
                ),
                capabilities=(Capability.QUERY_DOCUMENTS,),
            ),
        ),
    )


def _evidence() -> GroundedEvidence:
    return GroundedEvidence(
        evidence_id="ev_1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        document_title="authorized-evaluation.pdf",
        excerpt="Orion FY2025 revenue was INR 150 crore.",
        page_number=1,
        sheet_name=None,
        row_start=None,
        row_end=None,
        cell_start=None,
        cell_end=None,
    )


async def _run() -> tuple[_Check, ...]:
    if os.environ.get("RUN_LIVE_MODEL_EVAL") != "1":
        raise RuntimeError("SET_RUN_LIVE_MODEL_EVAL_1")
    settings = get_settings()
    if settings.llm_provider != "openrouter_vertex" or settings.openrouter_api_key is None:
        raise RuntimeError("OPENROUTER_VERTEX_NOT_CONFIGURED")

    checks: list[_Check] = []
    router = create_intent_router(settings)
    intent_cases = (
        ("Could you pull Orion’s latest approved revenue figure?", RequestIntent.DOCUMENT_QUESTION),
        ("What caused that increase?", RequestIntent.CONVERSATION_FOLLOW_UP),
        ("Please retain my preference for concise risk bullets.", RequestIntent.MEMORY_WRITE),
    )
    intent_results = [
        await router.classify(
            query=query,
            scope_allowed=True,
            has_recent_conversation=True,
        )
        for query, _ in intent_cases
    ]
    checks.append(
        _Check(
            "intent_accuracy",
            all(
                result.intent is expected
                for result, (_, expected) in zip(intent_results, intent_cases, strict=True)
            ),
        )
    )

    scope = _scope()
    catalog = ApprovedToolGateway.permitted_catalog(scope, APPROVED_TOOL_NAMES)
    perception_provider, decision_provider = create_agent_stage_providers(settings)
    query = "Calculate Orion debt-to-equity for FY2025."
    perception = await perception_provider.perceive_user_query(query=query)
    initial = await decision_provider.decide_initial(
        query=query,
        perception=perception,
        permitted_tool_catalog=catalog,
    )
    checks.extend(
        (
            _Check(
                "tool_selection",
                initial.next_action.action_name == "portfolio.calculate_debt_to_equity",
            ),
            _Check("perception_intent", perception.intent.value == "calculation_required"),
        )
    )

    search_query = "Explain Orion FY2025 revenue."
    search_perception = await perception_provider.perceive_user_query(query=search_query)
    search_initial = await decision_provider.decide_initial(
        query=search_query,
        perception=search_perception,
        permitted_tool_catalog=catalog,
    )
    if search_initial.next_action.action_name != "portfolio.search_authorized_documents":
        checks.extend((_Check("query_rewriting", False), _Check("replanning", False)))
    else:
        plan_state = PlanState.initial(search_initial).complete_next(search_initial.next_action)
        failed = StructuredObservation(
            tool_name="portfolio.search_authorized_documents",
            status=ObservationStatus.SUCCESS,
            duration_ms=1,
            reason_code="TOOL_COMPLETED",
        )
        failed_perception = await perception_provider.perceive_step_result(
            query=search_query,
            previous=search_perception,
            current_plan=plan_state.current_plan,
            completed_steps=plan_state.completed_history,
            observation=failed,
            remaining_budgets=RemainingBudgets(
                tool_steps=3,
                retrieval_rewrites=1,
                replans=1,
                latest_tool_retries=1,
                duration_ms=20_000,
            ),
        )
        revised = await decision_provider.decide_mid_session(
            query=search_query,
            perception=failed_perception,
            current_plan=plan_state.current_plan,
            completed_steps=plan_state.completed_history,
            permitted_tool_catalog=catalog,
        )
        original_arguments = search_initial.next_action.arguments.model_dump(mode="json")
        revised_arguments = revised.next_action.arguments.model_dump(mode="json")
        checks.extend(
            (
                _Check(
                    "query_rewriting",
                    revised.next_action.action_name == "portfolio.search_authorized_documents"
                    and revised_arguments != original_arguments,
                ),
                _Check("replanning", revised.replan and revised.plan.version == 2),
            )
        )

    evidence = _evidence()
    successful = StructuredObservation(
        tool_name="portfolio.search_authorized_documents",
        status=ObservationStatus.SUCCESS,
        evidence=(evidence,),
        duration_ms=1,
        reason_code="TOOL_COMPLETED",
    )
    success_state = PlanState.initial(search_initial).complete_next(search_initial.next_action)
    success_perception = await perception_provider.perceive_step_result(
        query=search_query,
        previous=search_perception,
        current_plan=success_state.current_plan,
        completed_steps=success_state.completed_history,
        observation=successful,
        remaining_budgets=RemainingBudgets(
            tool_steps=3,
            retrieval_rewrites=1,
            replans=1,
            latest_tool_retries=1,
            duration_ms=20_000,
        ),
    )
    stopping = await decision_provider.decide_mid_session(
        query=search_query,
        perception=success_perception,
        current_plan=success_state.current_plan,
        completed_steps=success_state.completed_history,
        permitted_tool_catalog=catalog,
    )
    checks.extend(
        (
            _Check(
                "goal_progress_judgement",
                success_perception.evidence_status is EvidenceStatus.SUFFICIENT
                and success_perception.global_goal_status is GoalStatus.SATISFIED,
            ),
            _Check("stopping", stopping.next_action.type is ActionType.FINALIZE),
        )
    )

    generation = await create_agent_finalizer(settings).generate(
        GroundedGenerationRequest(question=search_query, evidence=(evidence,))
    )
    checks.append(
        _Check(
            "citation_faithfulness",
            generation.answer.status == "supported"
            and bool(generation.answer.claims)
            and all(claim.evidence_ids == ("ev_1",) for claim in generation.answer.claims),
        )
    )

    extractor = create_memory_extractor(settings)
    candidates = await extractor.extract(
        MemoryExtractionRequest(
            user_text="Remember that I prefer financial values in INR crores.",
            assistant_text="Preference acknowledged.",
            conversation_id=uuid4(),
            source_message_id=uuid4(),
        )
    )
    checks.append(
        _Check(
            "memory_candidate_quality",
            len(candidates) == 1
            and candidates[0].explicit
            and candidates[0].memory_type == "SEMANTIC"
            and candidates[0].sensitivity.upper() in {"LOW", "NONE"},
        )
    )
    summary = await create_conversation_summarizer(settings).summarize(
        ConversationSummaryRequest(
            messages=(
                ("user", "Investigate Orion operating margin."),
                ("assistant", "The investigation completed with current citations."),
                ("user", "Next compare it with FY2024."),
            )
        )
    )
    checks.append(_Check("conversation_summary", 1 <= len(summary) <= 1000))
    return tuple(checks)


def main() -> None:
    try:
        checks = asyncio.run(_run())
    except Exception as exc:
        print(json.dumps({"status": "error", "safe_error_code": type(exc).__name__}))
        raise SystemExit(1) from None
    for check in checks:
        print(json.dumps({"check": check.name, "passed": check.passed}, separators=(",", ":")))
    if not all(check.passed for check in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
