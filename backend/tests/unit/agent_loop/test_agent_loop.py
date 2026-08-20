from uuid import uuid4

import pytest

from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.fake import (
    DeterministicFakeDecisionProvider,
    DeterministicFakeGateway,
    DeterministicFakePerceptionProvider,
)
from app.agent.loop import AgentLoop
from app.agent.models import (
    Action,
    ActionType,
    AgentLoopLimits,
    DecisionResult,
    EvidenceStatus,
    GoalStatus,
    ObservationStatus,
    PerceptionMode,
    PerceptionSnapshot,
    Plan,
    Step,
    StoppingReason,
    StructuredObservation,
    TerminalStatus,
)
from app.chat.contracts import GroundedAnswerDraft, GroundedClaimDraft, GroundedEvidence
from app.chat.fake import DeterministicFakeLLMProvider
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationContext,
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)

TOOL = "portfolio.search_authorized_documents"


def _context() -> AuthorizationContext:
    identity = TrustedIdentity(
        user_id=uuid4(), email="agent@example.com", display_name="Agent Test"
    )
    scope = AuthorizationScope(
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
    return AuthorizationContext(identity=identity, scope=scope)


def _perception(
    mode: PerceptionMode, status: EvidenceStatus = EvidenceStatus.NONE
) -> PerceptionSnapshot:
    return PerceptionSnapshot(
        mode=mode,
        intent="document_lookup",
        domain="portfolio_documents",
        entities=(),
        result_requirement="grounded_answer",
        required_capabilities=("QUERY_DOCUMENTS",),
        evidence_status=status,
        local_goal_status=GoalStatus.ADVANCED
        if mode == PerceptionMode.STEP_RESULT
        else GoalStatus.PENDING,
        global_goal_status=GoalStatus.SATISFIED
        if status == EvidenceStatus.SUFFICIENT
        else GoalStatus.PENDING,
        confidence=0.9,
        reason_code="EVIDENCE_ASSESSED",
    )


def _decision(action: Action, *, version: int = 1, replan: bool = False) -> DecisionResult:
    return DecisionResult(
        plan=Plan(
            version=version,
            steps=(
                Step(
                    step_index=0,
                    action_type=action.type,
                    action_name=action.action_name,
                    reason_code="BOUNDED_STEP",
                ),
            ),
            change_reason_code="PLAN_CREATED",
        ),
        next_action=action,
        replan=replan,
    )


def _tool_action(name: str = TOOL) -> Action:
    return Action(
        type=ActionType.TOOL_CALL,
        action_name=name,
        arguments={"query": "synthetic revenue", "top_k": 2},
        reason_code="SEARCH_EVIDENCE",
    )


def _terminal(action_type: ActionType) -> DecisionResult:
    return _decision(Action(type=action_type, reason_code=f"{action_type.value}_REQUEST"))


def _evidence() -> GroundedEvidence:
    return GroundedEvidence(
        evidence_id="ev_1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        document_title="synthetic.pdf",
        excerpt="Authorized synthetic revenue was 10.",
        page_number=1,
        sheet_name=None,
        row_start=None,
        row_end=None,
        cell_start=None,
        cell_end=None,
    )


def _observation(
    status: ObservationStatus, *, evidence: tuple[GroundedEvidence, ...] = (), retry_count: int = 0
) -> StructuredObservation:
    return StructuredObservation(
        tool_name=TOOL,
        status=status,
        evidence=evidence,
        duration_ms=2,
        retryable=status in {ObservationStatus.TIMEOUT, ObservationStatus.ERROR},
        retry_count=retry_count,
        reason_code=f"TOOL_{status.value.upper()}",
    )


def _loop(
    perceptions: tuple,
    decisions: tuple,
    observations: tuple = (),
    *,
    limits: AgentLoopLimits | None = None,
    clock=None,
    final_answer: GroundedAnswerDraft | None = None,
) -> AgentLoop:
    kwargs = {} if clock is None else {"clock": clock}
    return AgentLoop(
        perception=DeterministicFakePerceptionProvider(perceptions),
        decision=DeterministicFakeDecisionProvider(decisions),
        gateway=DeterministicFakeGateway(observations),
        finalizer=DeterministicFakeLLMProvider(final_answer),
        limits=limits,
        **kwargs,
    )


async def _run(loop: AgentLoop, tools: frozenset[str] = frozenset({TOOL})):
    return await loop.run(
        query="What was synthetic revenue?",
        authorization_context=_context(),
        permitted_tools=tools,
        request_id="request-agent-test",
    )


@pytest.mark.asyncio
async def test_successful_flow_returns_to_perception_and_preserves_citations() -> None:
    result = await _run(
        _loop(
            (
                _perception(PerceptionMode.USER_QUERY),
                _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.SUFFICIENT),
            ),
            (_decision(_tool_action()), _terminal(ActionType.FINALIZE)),
            (_observation(ObservationStatus.SUCCESS, evidence=(_evidence(),), retry_count=1),),
            final_answer=GroundedAnswerDraft(
                "supported", (GroundedClaimDraft("Synthetic revenue was 10.", ("ev_1",)),)
            ),
        )
    )
    assert result.terminal_status == TerminalStatus.COMPLETED
    assert result.citations[0].citation_id == "ev_1"
    assert result.retry_count == 1
    assert [item.event_type.value for item in result.trace][-3:] == [
        "finalization",
        "finalization",
        "terminal",
    ]
    serialized = [item.model_dump(mode="json") for item in result.trace]
    assert all(
        set(item)
        == {
            "event_id",
            "event_type",
            "action_name",
            "status",
            "duration_ms",
            "evidence_reference_ids",
            "reason_code",
        }
        for item in serialized
    )
    assert "synthetic revenue" not in str(serialized).casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action_type", "status", "reason"),
    [
        (
            ActionType.CLARIFY,
            TerminalStatus.NEEDS_CLARIFICATION,
            StoppingReason.CLARIFICATION_REQUIRED,
        ),
        (ActionType.REFUSE, TerminalStatus.REFUSED, StoppingReason.REQUEST_REFUSED),
        (
            ActionType.FINALIZE,
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            StoppingReason.INSUFFICIENT_AUTHORIZED_EVIDENCE,
        ),
    ],
)
async def test_direct_terminal_paths(
    action_type: ActionType, status: TerminalStatus, reason: StoppingReason
) -> None:
    result = await _run(_loop((_perception(PerceptionMode.USER_QUERY),), (_terminal(action_type),)))
    assert (result.terminal_status, result.stopping_reason) == (status, reason)


@pytest.mark.asyncio
async def test_unknown_or_unshortlisted_tool_denied_before_gateway() -> None:
    result = await _run(
        _loop(
            (_perception(PerceptionMode.USER_QUERY),),
            (_decision(_tool_action("portfolio.unknown")),),
        ),
        frozenset({TOOL}),
    )
    assert result.terminal_status == TerminalStatus.REFUSED
    assert result.stopping_reason == StoppingReason.SCOPE_DENIED
    assert result.step_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observation", "status", "reason"),
    [
        (
            _observation(ObservationStatus.DENIED),
            TerminalStatus.REFUSED,
            StoppingReason.SCOPE_DENIED,
        ),
        (
            _observation(ObservationStatus.TIMEOUT, retry_count=1),
            TerminalStatus.FAILED,
            StoppingReason.TOOL_TIMEOUT,
        ),
        (
            _observation(ObservationStatus.ERROR, retry_count=1),
            TerminalStatus.FAILED,
            StoppingReason.TOOL_ERROR,
        ),
    ],
)
async def test_gateway_failure_paths_are_explicit(
    observation: StructuredObservation, status: TerminalStatus, reason: StoppingReason
) -> None:
    result = await _run(
        _loop(
            (_perception(PerceptionMode.USER_QUERY),), (_decision(_tool_action()),), (observation,)
        )
    )
    assert (result.terminal_status, result.stopping_reason) == (status, reason)
    if observation.status == ObservationStatus.DENIED:
        assert result.retry_count == 0


@pytest.mark.asyncio
async def test_max_steps_and_max_replans_terminate() -> None:
    perceptions = (_perception(PerceptionMode.USER_QUERY), _perception(PerceptionMode.STEP_RESULT))
    decisions = (_decision(_tool_action()), _decision(_tool_action(), version=2, replan=True))
    result = await _run(
        _loop(
            perceptions,
            decisions,
            (_observation(ObservationStatus.SUCCESS),),
            limits=AgentLoopLimits(max_steps=1, max_replans=1, max_duration_seconds=30),
        )
    )
    assert result.stopping_reason == StoppingReason.MAX_STEPS

    decisions = (_decision(_tool_action()), _decision(_tool_action(), version=2, replan=True))
    result = await _run(
        _loop(
            perceptions,
            decisions,
            (_observation(ObservationStatus.SUCCESS),),
            limits=AgentLoopLimits(max_steps=4, max_replans=0, max_duration_seconds=30),
        )
    )
    assert result.stopping_reason == StoppingReason.MAX_REPLANS


@pytest.mark.asyncio
async def test_duration_model_and_citation_failures_terminate_safely() -> None:
    ticks = iter((0.0, 31.0, 31.0, 31.0))
    result = await _run(
        _loop(
            (_perception(PerceptionMode.USER_QUERY),),
            (),
            limits=AgentLoopLimits(max_duration_seconds=30),
            clock=lambda: next(ticks),
        )
    )
    assert result.stopping_reason == StoppingReason.MAX_DURATION

    result = await _run(_loop((AgentModelError(AgentModelErrorCode.INVALID_RESPONSE),), ()))
    assert result.stopping_reason == StoppingReason.MODEL_ERROR

    result = await _run(
        _loop(
            (
                _perception(PerceptionMode.USER_QUERY),
                _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.SUFFICIENT),
            ),
            (_decision(_tool_action()), _terminal(ActionType.FINALIZE)),
            (_observation(ObservationStatus.SUCCESS, evidence=(_evidence(),)),),
            final_answer=GroundedAnswerDraft(
                "supported", (GroundedClaimDraft("Unsupported.", ("ev_missing",)),)
            ),
        )
    )
    assert result.terminal_status == TerminalStatus.INSUFFICIENT_EVIDENCE
    assert result.stopping_reason == StoppingReason.CITATION_VALIDATION_FAILED


def test_action_schema_rejects_forged_scope_and_execution_arguments() -> None:
    for key in (
        "tenant_id",
        "company_ids",
        "department",
        "user_role",
        "sql_query",
        "python_code",
        "url",
        "file_path",
    ):
        with pytest.raises(ValueError):
            Action(
                type=ActionType.TOOL_CALL,
                action_name=TOOL,
                arguments={key: "forged"},
                reason_code="FORGED",
            )
