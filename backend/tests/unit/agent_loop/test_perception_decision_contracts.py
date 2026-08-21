import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.models import (
    Action,
    ActionType,
    CompletedStep,
    EvidenceStatus,
    GoalStatus,
    MentionedScopeHints,
    ObservationStatus,
    PerceptionEntities,
    PerceptionIntent,
    PerceptionMode,
    PerceptionRiskFlag,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    RequiredEvidence,
    ResultRequirement,
    Step,
    StepStatus,
    StructuredObservation,
)
from app.agent.prompts import (
    PERCEPTION_SYSTEM_INSTRUCTION,
    initial_decision_prompt,
    step_result_perception_prompt,
)
from app.agent.provider_schema import provider_schema
from app.agent.rule_based_fake import RuleBasedFakeAgentProvider
from app.mcp_gateway.contracts import (
    APPROVED_TOOL_NAMES,
    GetDocumentExcerptInput,
    SearchAuthorizedDocumentsInput,
)
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)

SEARCH = "portfolio.search_authorized_documents"
EXCERPT = "portfolio.get_document_excerpt"


def _scope() -> AuthorizationScope:
    identity = TrustedIdentity(user_id=uuid4(), email="owner@example.com", display_name="Owner")
    return AuthorizationScope(
        identity=identity,
        grants=(
            AuthorizationGrant(
                membership_id=uuid4(),
                home_tenant_id=uuid4(),
                home_tenant_slug="orion",
                home_tenant_name="Orion",
                workspace_id=uuid4(),
                workspace_slug="orion",
                workspace_name="Orion",
                role="analyst",
                primary_department="finance",
                company_ids=(uuid4(),),
                company_slugs=("orion",),
                departments=(
                    DepartmentAccess(key="finance", source=GrantSource.PRIMARY_DEPARTMENT),
                ),
                capabilities=(Capability.QUERY_DOCUMENTS,),
            ),
        ),
    )


def _perception(mode: PerceptionMode = PerceptionMode.USER_QUERY) -> PerceptionSnapshot:
    return PerceptionSnapshot(
        mode=mode,
        intent=PerceptionIntent.FINANCIAL_LOOKUP,
        domain="portfolio_documents",
        entities=PerceptionEntities(
            companies=("Orion",),
            financial_metrics=("revenue",),
            reporting_periods=("FY2025",),
        ),
        mentioned_scope_hints=MentionedScopeHints(companies=("Orion",)),
        result_requirement=ResultRequirement.GROUNDED_ANSWER,
        required_evidence=(RequiredEvidence.FINANCIAL_DOCUMENT,),
        required_capabilities=("QUERY_DOCUMENTS",),
        risk_flags=(PerceptionRiskFlag.SCOPE_HINT_PRESENT,),
        evidence_status=EvidenceStatus.NONE,
        local_goal_status=GoalStatus.PENDING,
        global_goal_status=GoalStatus.PENDING,
        confidence=0.9,
        reason_code="FINANCIAL_LOOKUP_CLASSIFIED",
        rationale_summary="A bounded authorized document lookup is needed.",
    )


def _plan() -> Plan:
    return Plan(
        version=1,
        plan_text=("Search authorized documents.", "Finalize validated evidence."),
        steps=(
            Step(
                step_index=0,
                action_type=ActionType.TOOL_CALL,
                action_name=SEARCH,
                status=StepStatus.COMPLETED,
                reason_code="TOOL_COMPLETED",
            ),
            Step(step_index=1, action_type=ActionType.FINALIZE, reason_code="FINALIZE"),
        ),
        change_reason_code="PLAN_CREATED",
    )


@pytest.mark.asyncio
async def test_initial_perception_classifies_supported_domain_intents() -> None:
    provider = RuleBasedFakeAgentProvider()
    financial = await provider.perceive_user_query(query="Find Orion revenue in FY2025")
    legal = await provider.perceive_user_query(query="Find the authorized contract clause")
    calculation = await provider.perceive_user_query(query="Calculate EBITDA margin")

    assert financial.intent == PerceptionIntent.FINANCIAL_LOOKUP
    assert legal.intent == PerceptionIntent.LEGAL_LOOKUP
    assert calculation.intent == PerceptionIntent.CALCULATION_REQUIRED
    assert calculation.required_evidence == (RequiredEvidence.CALCULATION_INPUTS,)


def test_step_result_prompt_contains_only_required_state_and_safe_budgets() -> None:
    plan = _plan()
    completed = (
        CompletedStep(
            plan_version=1,
            step_index=0,
            action_type=ActionType.TOOL_CALL,
            action_name=SEARCH,
            reason_code="TOOL_COMPLETED",
        ),
    )
    observation = StructuredObservation(
        tool_name=SEARCH,
        status=ObservationStatus.SUCCESS,
        duration_ms=3,
        reason_code="TOOL_COMPLETED",
    )
    budgets = RemainingBudgets(
        tool_steps=3,
        retrieval_rewrites=1,
        replans=1,
        latest_tool_retries=1,
        duration_ms=80_000,
    )
    decoded = json.loads(
        step_result_perception_prompt(
            "Synthetic question", _perception(), plan, completed, observation, budgets
        )
    )

    assert set(decoded) == {
        "mode",
        "user_query",
        "previous_perception",
        "current_plan",
        "immutable_completed_step_history",
        "latest_untrusted_structured_observation",
        "safe_remaining_budgets",
    }
    serialized = json.dumps(decoded)
    for forbidden in ("authorization_scope", "user_id", "tenant_id", "api_key", "raw_error"):
        assert forbidden not in serialized
    assert "untrusted data" in PERCEPTION_SYSTEM_INSTRUCTION.casefold()


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "final_answer",
        "retry_recommendation",
        "facts_learned",
        "raw_citations",
        "document_ids",
        "solution_summary",
        "authorization_scope",
    ],
)
def test_perception_schema_rejects_answer_retry_fact_citation_and_scope_fields(
    forbidden_field: str,
) -> None:
    payload = _perception().model_dump(mode="json")
    payload[forbidden_field] = "forbidden"
    with pytest.raises(ValidationError):
        PerceptionSnapshot.model_validate(payload, strict=True)


def test_provider_schema_is_derived_bounded_and_strict_local_validation_remains() -> None:
    schema = provider_schema(PerceptionSnapshot)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == set(PerceptionSnapshot.model_fields)
    assert properties["ambiguities"]["maxItems"] == 5
    assert properties["rationale_summary"]["maxLength"] == 300
    assert properties["domain"]["enum"] == ["portfolio_documents"]
    assert properties["required_capabilities"]["items"]["enum"] == ["QUERY_DOCUMENTS"]


def test_decision_receives_exact_sanitized_manifest_catalog() -> None:
    catalog = ApprovedToolGateway.permitted_catalog(_scope(), APPROVED_TOOL_NAMES)
    decoded = json.loads(initial_decision_prompt("Synthetic question", _perception(), catalog))
    descriptors = decoded["permitted_tool_catalog"]

    assert [item["name"] for item in descriptors] == [SEARCH, EXCERPT]
    assert [field["name"] for field in descriptors[0]["input_schema"]["fields"]] == [
        "query",
        "top_k",
    ]
    assert [field["name"] for field in descriptors[1]["input_schema"]["fields"]] == [
        "document_id",
        "chunk_id",
    ]
    serialized = json.dumps(descriptors)
    for forbidden in ("tenant", "user_id", "role", "department", "sql", "path", "api_key"):
        assert forbidden not in serialized.casefold()


def test_tool_actions_reject_the_other_tools_arguments_and_extra_scope() -> None:
    excerpt_arguments = GetDocumentExcerptInput(document_id=uuid4(), chunk_id=uuid4())
    search_arguments = SearchAuthorizedDocumentsInput(query="authorized", top_k=2)

    with pytest.raises(ValidationError):
        Action(
            type=ActionType.TOOL_CALL,
            action_name=SEARCH,
            arguments=excerpt_arguments,
            reason_code="WRONG_SCHEMA",
        )
    with pytest.raises(ValidationError):
        Action(
            type=ActionType.TOOL_CALL,
            action_name=EXCERPT,
            arguments=search_arguments,
            reason_code="WRONG_SCHEMA",
        )
    with pytest.raises(ValidationError):
        Action.model_validate(
            {
                "type": "TOOL_CALL",
                "action_name": SEARCH,
                "arguments": {"query": "authorized", "top_k": 2, "tenant_id": "forged"},
                "reason_code": "FORGED_SCOPE",
            },
            strict=True,
        )
