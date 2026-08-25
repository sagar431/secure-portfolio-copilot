from uuid import UUID, uuid4

import pytest

from app.agent.approval_security import canonical_action_hash
from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.fake import (
    DeterministicFakeDecisionProvider,
    DeterministicFakeGateway,
    DeterministicFakePerceptionProvider,
)
from app.agent.loop import AgentLoop, ReconstructedStep
from app.agent.models import (
    Action,
    ActionType,
    AgentLoopLimits,
    DecisionResult,
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
    RequiredEvidence,
    ResultRequirement,
    Step,
    StepStatus,
    StoppingReason,
    StructuredObservation,
    TerminalStatus,
)
from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedClaimDraft,
    GroundedEvidence,
    GroundedMemory,
    GroundedWorkingMessage,
)
from app.chat.fake import DeterministicFakeLLMProvider
from app.mcp_gateway.contracts import (
    APPROVED_TOOL_NAMES,
    GetDocumentExcerptInput,
    MemoryToolItem,
    ProposeMemoryInput,
    SearchAuthorizedDocumentsInput,
    SearchMemoryInput,
)
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.models.agent_runs import AgentControlMode
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationContext,
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)

SEARCH = "portfolio.search_authorized_documents"
EXCERPT = "portfolio.get_document_excerpt"


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


def _catalog(context: AuthorizationContext):  # type: ignore[no-untyped-def]
    return ApprovedToolGateway.permitted_catalog(context.scope, APPROVED_TOOL_NAMES)


def _perception(
    mode: PerceptionMode,
    status: EvidenceStatus = EvidenceStatus.NONE,
    *,
    hints: MentionedScopeHints | None = None,
) -> PerceptionSnapshot:
    return PerceptionSnapshot(
        mode=mode,
        intent=PerceptionIntent.FINANCIAL_LOOKUP,
        domain="portfolio_documents",
        entities=PerceptionEntities(financial_metrics=("revenue",)),
        mentioned_scope_hints=hints or MentionedScopeHints(),
        result_requirement=ResultRequirement.GROUNDED_ANSWER,
        required_evidence=(RequiredEvidence.FINANCIAL_DOCUMENT,),
        required_capabilities=("QUERY_DOCUMENTS",),
        risk_flags=(PerceptionRiskFlag.SCOPE_HINT_PRESENT,) if hints else (),
        evidence_status=status,
        local_goal_status=(
            GoalStatus.ADVANCED if mode == PerceptionMode.STEP_RESULT else GoalStatus.PENDING
        ),
        global_goal_status=(
            GoalStatus.SATISFIED if status == EvidenceStatus.SUFFICIENT else GoalStatus.PENDING
        ),
        confidence=0.9,
        reason_code="EVIDENCE_ASSESSED",
        rationale_summary="A concise internal assessment.",
    )


def _search(query: str = "synthetic revenue") -> Action:
    return Action(
        type=ActionType.TOOL_CALL,
        action_name=SEARCH,
        arguments=SearchAuthorizedDocumentsInput(query=query, top_k=2),
        reason_code="SEARCH_EVIDENCE",
    )


def _excerpt(document_id: UUID | None = None, chunk_id: UUID | None = None) -> Action:
    return Action(
        type=ActionType.TOOL_CALL,
        action_name=EXCERPT,
        arguments=GetDocumentExcerptInput(
            document_id=document_id or uuid4(), chunk_id=chunk_id or uuid4()
        ),
        reason_code="GET_EXCERPT",
    )


def _terminal_action(action_type: ActionType) -> Action:
    return Action(type=action_type, reason_code=f"{action_type.value}_REQUEST")


def _plan(actions: tuple[Action, ...], *, version: int = 1, completed: int = 0) -> Plan:
    return Plan(
        version=version,
        plan_text=tuple(f"Bounded plan step {index}." for index in range(len(actions))),
        steps=tuple(
            Step(
                step_index=index,
                action_type=action.type,
                action_name=action.action_name,
                status=StepStatus.COMPLETED if index < completed else StepStatus.PENDING,
                reason_code="TOOL_COMPLETED" if index < completed else "BOUNDED_STEP",
            )
            for index, action in enumerate(actions)
        ),
        change_reason_code="PLAN_CREATED" if version == 1 else "PLAN_REVISED",
    )


def _decision(
    actions: tuple[Action, ...],
    next_index: int,
    *,
    version: int = 1,
    completed: int = 0,
    replan: bool = False,
) -> DecisionResult:
    return DecisionResult(
        plan=_plan(actions, version=version, completed=completed),
        next_action=actions[next_index],
        replan=replan,
    )


def _evidence(evidence_id: str = "ev_1") -> GroundedEvidence:
    return GroundedEvidence(
        evidence_id=evidence_id,
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
    tool: str,
    status: ObservationStatus = ObservationStatus.SUCCESS,
    *,
    evidence: tuple[GroundedEvidence, ...] = (),
    retry_count: int = 0,
) -> StructuredObservation:
    return StructuredObservation(
        tool_name=tool,
        status=status,
        evidence=evidence,
        duration_ms=2,
        retryable=status in {ObservationStatus.TIMEOUT, ObservationStatus.ERROR},
        retry_count=retry_count,
        reason_code=f"TOOL_{status.value.upper()}",
    )


def _loop(
    perceptions: tuple[PerceptionSnapshot | AgentModelError, ...],
    decisions: tuple[DecisionResult | AgentModelError, ...],
    observations: tuple[StructuredObservation, ...] = (),
    *,
    limits: AgentLoopLimits | None = None,
    clock=None,
    final_answer: GroundedAnswerDraft | None = None,
) -> tuple[AgentLoop, DeterministicFakePerceptionProvider, DeterministicFakeGateway]:
    perception = DeterministicFakePerceptionProvider(perceptions)
    gateway = DeterministicFakeGateway(observations)
    kwargs = {} if clock is None else {"clock": clock}
    loop = AgentLoop(
        perception=perception,
        decision=DeterministicFakeDecisionProvider(decisions),
        gateway=gateway,
        finalizer=DeterministicFakeLLMProvider(final_answer),
        limits=limits,
        **kwargs,
    )
    return loop, perception, gateway


async def _run(loop: AgentLoop, context: AuthorizationContext | None = None):  # type: ignore[no-untyped-def]
    active_context = context or _context()
    return await loop.run(
        query="What was synthetic revenue?",
        authorization_context=active_context,
        permitted_tool_catalog=_catalog(active_context),
        request_id="request-agent-test",
    )


@pytest.mark.asyncio
async def test_real_two_step_plan_executes_search_excerpt_then_finalization_in_order() -> None:
    search = _search()
    evidence = _evidence()
    excerpt = _excerpt(evidence.document_id, evidence.chunk_id)
    finalize = _terminal_action(ActionType.FINALIZE)
    actions = (search, excerpt, finalize)
    loop, perception, gateway = _loop(
        (
            _perception(PerceptionMode.USER_QUERY),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.INSUFFICIENT),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.SUFFICIENT),
        ),
        (
            _decision(actions, 0),
            _decision(actions, 1, completed=1),
            _decision(actions, 2, completed=2),
        ),
        (
            _observation(SEARCH, evidence=(evidence,)),
            _observation(EXCERPT, evidence=(_evidence("ev_2"),)),
        ),
        final_answer=GroundedAnswerDraft(
            "supported", (GroundedClaimDraft("Synthetic revenue was 10.", ("ev_2",)),)
        ),
    )
    result = await _run(loop)

    assert result.terminal_status == TerminalStatus.COMPLETED
    assert [call[0] for call in gateway.calls] == [SEARCH, EXCERPT]
    assert perception.step_result_calls == 2
    assert perception.step_result_inputs[0][2].steps[0].status == StepStatus.COMPLETED
    assert len(perception.step_result_inputs[1][3]) == 2
    assert result.citations[0].citation_id == "ev_2"


@pytest.mark.asyncio
async def test_guided_resume_replays_completed_step_and_calls_only_approved_next_tool() -> None:
    search = _search()
    first_evidence = _evidence()
    excerpt = _excerpt(first_evidence.document_id, first_evidence.chunk_id)
    finalize = _terminal_action(ActionType.FINALIZE)
    actions = (search, excerpt, finalize)
    first_observation = _observation(SEARCH, evidence=(first_evidence,))
    loop, _, gateway = _loop(
        (
            _perception(PerceptionMode.USER_QUERY),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.INSUFFICIENT),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.SUFFICIENT),
        ),
        (
            _decision(actions, 0),
            _decision(actions, 1, completed=1),
            _decision(actions, 2, completed=2),
        ),
        (_observation(EXCERPT, evidence=(_evidence("ev_2"),)),),
        final_answer=GroundedAnswerDraft(
            "supported", (GroundedClaimDraft("Supported.", ("ev_2",)),)
        ),
    )
    context = _context()
    result = await loop.run(
        query="What was synthetic revenue?",
        authorization_context=context,
        permitted_tool_catalog=_catalog(context),
        request_id="guided-reconstruction",
        agent_control_mode=AgentControlMode.GUIDED,
        approved_action_hash=canonical_action_hash(excerpt),
        reconstructed_steps=(
            ReconstructedStep(
                action_hash=canonical_action_hash(search), observation=first_observation
            ),
        ),
    )

    assert result.terminal_status == TerminalStatus.COMPLETED
    assert [call[0] for call in gateway.calls] == [EXCERPT]


@pytest.mark.asyncio
async def test_scope_hints_remain_advisory_and_never_reach_tool_arguments_or_authority() -> None:
    hints = MentionedScopeHints(tenants=("atlas",), companies=("atlas",), departments=("legal",))
    search = _search()
    clarify = _terminal_action(ActionType.CLARIFY)
    actions = (search, clarify)
    context = _context()
    loop, _, gateway = _loop(
        (
            _perception(PerceptionMode.USER_QUERY, hints=hints),
            _perception(PerceptionMode.STEP_RESULT, hints=hints),
        ),
        (_decision(actions, 0), _decision(actions, 1, completed=1)),
        (_observation(SEARCH),),
    )
    await _run(loop, context)

    assert gateway.calls[0][1] is context
    assert search.arguments.model_dump() == {"query": "synthetic revenue", "top_k": 2}


@pytest.mark.asyncio
async def test_insufficient_evidence_allows_one_replan_and_one_search_rewrite() -> None:
    first = _search("first authorized search")
    rewrite = _search("one safe rewritten search")
    clarify = _terminal_action(ActionType.CLARIFY)
    initial_actions = (first,)
    revised_actions = (rewrite, clarify)
    loop, perception, gateway = _loop(
        (
            _perception(PerceptionMode.USER_QUERY),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.INSUFFICIENT),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.INSUFFICIENT),
        ),
        (
            _decision(initial_actions, 0),
            _decision(revised_actions, 0, version=2),
            _decision(revised_actions, 1, version=2, completed=1),
        ),
        (_observation(SEARCH), _observation(SEARCH)),
    )
    result = await _run(loop)

    assert result.terminal_status == TerminalStatus.NEEDS_CLARIFICATION
    assert result.replan_count == 1
    assert len(gateway.calls) == 2
    assert perception.step_result_inputs[1][3][0].plan_version == 1


@pytest.mark.asyncio
async def test_third_search_is_blocked_by_semantic_rewrite_limit() -> None:
    actions = (_search("one"), _search("two"), _search("three"))
    loop, _, gateway = _loop(
        (
            _perception(PerceptionMode.USER_QUERY),
            _perception(PerceptionMode.STEP_RESULT),
            _perception(PerceptionMode.STEP_RESULT),
        ),
        (
            _decision(actions, 0),
            _decision(actions, 1, completed=1),
            _decision(actions, 2, completed=2),
        ),
        (_observation(SEARCH), _observation(SEARCH)),
    )
    result = await _run(loop)

    assert result.stopping_reason == StoppingReason.MAX_RETRIEVAL_REWRITES
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_plan_exhaustion_and_out_of_order_action_fail_before_gateway() -> None:
    search = _search()
    finalize = _terminal_action(ActionType.FINALIZE)
    loop, _, gateway = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (_decision((search, finalize), 1),),
    )
    out_of_order = await _run(loop)
    assert out_of_order.stopping_reason == StoppingReason.MALFORMED_ACTION
    assert gateway.calls == []

    loop, _, gateway = _loop(
        (_perception(PerceptionMode.USER_QUERY), _perception(PerceptionMode.STEP_RESULT)),
        (
            _decision((search,), 0),
            DecisionResult(plan=_plan((search,), completed=1), next_action=finalize),
        ),
        (_observation(SEARCH),),
    )
    exhausted = await _run(loop)
    assert exhausted.stopping_reason == StoppingReason.PLAN_EXHAUSTED
    assert len(gateway.calls) == 1


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
async def test_direct_terminal_paths_are_safe(
    action_type: ActionType, status: TerminalStatus, reason: StoppingReason
) -> None:
    action = _terminal_action(action_type)
    loop, _, _ = _loop((_perception(PerceptionMode.USER_QUERY),), (_decision((action,), 0),))
    result = await _run(loop)
    assert (result.terminal_status, result.stopping_reason) == (status, reason)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observation", "status", "reason"),
    [
        (
            _observation(SEARCH, ObservationStatus.DENIED),
            TerminalStatus.REFUSED,
            StoppingReason.SCOPE_DENIED,
        ),
        (
            _observation(SEARCH, ObservationStatus.TIMEOUT, retry_count=1),
            TerminalStatus.FAILED,
            StoppingReason.TOOL_TIMEOUT,
        ),
        (
            _observation(SEARCH, ObservationStatus.ERROR, retry_count=1),
            TerminalStatus.FAILED,
            StoppingReason.TOOL_ERROR,
        ),
    ],
)
async def test_gateway_failure_paths_are_explicit(
    observation: StructuredObservation,
    status: TerminalStatus,
    reason: StoppingReason,
) -> None:
    search = _search()
    loop, _, _ = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (_decision((search,), 0),),
        (observation,),
    )
    result = await _run(loop)
    assert (result.terminal_status, result.stopping_reason) == (status, reason)


@pytest.mark.asyncio
async def test_model_duration_and_citation_failures_terminate_safely() -> None:
    ticks = iter((0.0, 31.0, 31.0, 31.0))
    loop, _, _ = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (),
        limits=AgentLoopLimits(max_duration_seconds=30),
        clock=lambda: next(ticks),
    )
    assert (await _run(loop)).stopping_reason == StoppingReason.MAX_DURATION

    loop, _, _ = _loop((AgentModelError(AgentModelErrorCode.INVALID_RESPONSE),), ())
    assert (await _run(loop)).stopping_reason == StoppingReason.MODEL_ERROR

    evidence = _evidence()
    search = _search()
    finalize = _terminal_action(ActionType.FINALIZE)
    actions = (search, finalize)
    loop, _, _ = _loop(
        (
            _perception(PerceptionMode.USER_QUERY),
            _perception(PerceptionMode.STEP_RESULT, EvidenceStatus.SUFFICIENT),
        ),
        (_decision(actions, 0), _decision(actions, 1, completed=1)),
        (_observation(SEARCH, evidence=(evidence,)),),
        final_answer=GroundedAnswerDraft(
            "supported", (GroundedClaimDraft("Unsupported.", ("ev_missing",)),)
        ),
    )
    result = await _run(loop)
    assert result.stopping_reason == StoppingReason.CITATION_VALIDATION_FAILED


def test_loop_exposes_no_unrestricted_execution_methods() -> None:
    assert set(AgentLoop.__dict__).isdisjoint({"run_user_code", "execute_python", "execute_sql"})


@pytest.mark.asyncio
async def test_loop_binds_bounded_working_semantic_and_summary_context_before_perception() -> None:
    clarify = _terminal_action(ActionType.CLARIFY)
    loop, perception, _ = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (_decision((clarify,), 0),),
    )
    memory = GroundedMemory(
        memory_id=uuid4(),
        scope="PRIVATE_USER",
        memory_type="SEMANTIC",
        content="Prefer INR crores.",
    )
    recent = (GroundedWorkingMessage(role="user", content="Earlier margin question"),)
    context = _context()

    await loop.run(
        query="Continue that work.",
        authorization_context=context,
        permitted_tool_catalog=_catalog(context),
        request_id="request-working-context-test",
        memories=(memory,),
        recent_messages=recent,
        conversation_summary="Investigating operating margin.",
    )

    assert perception.request_context.memories == (memory,)
    assert perception.request_context.recent_messages == recent
    assert perception.request_context.conversation_summary == "Investigating operating margin."


@pytest.mark.asyncio
async def test_memory_search_finalizes_as_prior_context_without_document_citations() -> None:
    action = Action(
        type=ActionType.TOOL_CALL,
        action_name="portfolio.search_memory",
        arguments=SearchMemoryInput(query="last investigation", mode="latest_episode", top_k=1),
        reason_code="SEARCH_AUTHORIZED_MEMORY",
    )
    observation = StructuredObservation(
        tool_name="portfolio.search_memory",
        status=ObservationStatus.SUCCESS,
        memory_context=(
            MemoryToolItem(
                memory_id=uuid4(),
                memory_type="EPISODIC",
                scope="PRIVATE_USER",
                summary="Investigated Orion operating margin.",
                source_count=1,
            ),
        ),
        duration_ms=1,
        reason_code="TOOL_COMPLETED",
    )
    loop, perception, _ = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (_decision((action,), 0),),
        (observation,),
    )
    result = await _run(loop)

    assert result.terminal_status == TerminalStatus.COMPLETED
    assert "private memory/history" in result.answer
    assert "not current financial evidence" in result.answer
    assert result.citations == ()
    assert perception.step_result_calls == 0


@pytest.mark.asyncio
async def test_memory_proposal_returns_to_host_policy_without_direct_loop_write() -> None:
    proposal = ProposeMemoryInput(
        content="Present financial values in INR crores.",
        normalized_key="financial_value_format",
        explicit=True,
    )
    action = Action(
        type=ActionType.TOOL_CALL,
        action_name="portfolio.propose_memory",
        arguments=proposal,
        reason_code="PROPOSE_MEMORY_TO_HOST_POLICY",
    )
    observation = StructuredObservation(
        tool_name="portfolio.propose_memory",
        status=ObservationStatus.SUCCESS,
        memory_notification="Memory proposal sent to host policy",
        duration_ms=1,
        reason_code="TOOL_COMPLETED",
    )
    loop, perception, _ = _loop(
        (_perception(PerceptionMode.USER_QUERY),),
        (_decision((action,), 0),),
        (observation,),
    )
    context = _context()
    result = await loop.run(
        query="Remember my preference.",
        authorization_context=context,
        permitted_tool_catalog=_catalog(context),
        request_id="memory-proposal-test",
        approved_action_hash=canonical_action_hash(action),
    )

    assert result.terminal_status == TerminalStatus.COMPLETED
    assert result.memory_proposal == proposal
    assert perception.step_result_calls == 0
