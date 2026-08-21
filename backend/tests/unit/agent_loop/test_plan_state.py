from uuid import uuid4

import pytest

from app.agent.models import (
    Action,
    ActionType,
    DecisionResult,
    NoActionArguments,
    Plan,
    Step,
    StepStatus,
)
from app.agent.plan_state import PlanContractError, PlanExhaustedError, PlanState
from app.mcp_gateway.contracts import (
    GetDocumentExcerptInput,
    SearchAuthorizedDocumentsInput,
)

SEARCH = "portfolio.search_authorized_documents"
EXCERPT = "portfolio.get_document_excerpt"


def _search(query: str = "authorized revenue") -> Action:
    return Action(
        type=ActionType.TOOL_CALL,
        action_name=SEARCH,
        arguments=SearchAuthorizedDocumentsInput(query=query, top_k=3),
        reason_code="SEARCH_EVIDENCE",
    )


def _excerpt() -> Action:
    return Action(
        type=ActionType.TOOL_CALL,
        action_name=EXCERPT,
        arguments=GetDocumentExcerptInput(document_id=uuid4(), chunk_id=uuid4()),
        reason_code="GET_EXCERPT",
    )


def _finalize() -> Action:
    return Action(
        type=ActionType.FINALIZE,
        arguments=NoActionArguments(),
        reason_code="FINALIZE_EVIDENCE",
    )


def _plan(
    version: int,
    actions: tuple[Action, ...],
    *,
    statuses: tuple[StepStatus, ...] | None = None,
) -> Plan:
    statuses = statuses or tuple(StepStatus.PENDING for _ in actions)
    return Plan(
        version=version,
        plan_text=tuple(f"Bounded step {index}." for index in range(len(actions))),
        steps=tuple(
            Step(
                step_index=index,
                action_type=action.type,
                action_name=action.action_name,
                status=statuses[index],
                reason_code="BOUNDED_STEP",
            )
            for index, action in enumerate(actions)
        ),
        change_reason_code="PLAN_UPDATED",
    )


def _decision(plan: Plan, action: Action, *, replan: bool = False) -> DecisionResult:
    return DecisionResult(plan=plan, next_action=action, replan=replan)


def test_initial_plan_requires_version_one_and_matching_plan_text() -> None:
    action = _search()
    with pytest.raises(PlanContractError, match="version"):
        PlanState.initial(_decision(_plan(2, (action,)), action))
    with pytest.raises(ValueError, match="Plan text"):
        Plan(
            version=1,
            plan_text=("Only one entry.",),
            steps=(
                Step(
                    step_index=0,
                    action_type=ActionType.TOOL_CALL,
                    action_name=SEARCH,
                    reason_code="ONE",
                ),
                Step(step_index=1, action_type=ActionType.FINALIZE, reason_code="TWO"),
            ),
            change_reason_code="INVALID",
        )


def test_changed_plan_requires_exactly_one_version_increment() -> None:
    first = _search()
    state = PlanState.initial(_decision(_plan(1, (first,)), first)).complete_next(first)
    changed = _search("authorized revenue rewritten")

    for invalid_version in (1, 3, 9):
        with pytest.raises(PlanContractError, match="exactly one"):
            state.apply_decision(_decision(_plan(invalid_version, (changed,)), changed))

    updated, changed_flag = state.apply_decision(_decision(_plan(2, (changed,)), changed))
    assert changed_flag is True
    assert updated.current_plan.version == 2


def test_unchanged_plan_cannot_claim_replan_or_change_version() -> None:
    search = _search()
    finalize = _finalize()
    initial = _plan(1, (search, finalize))
    state = PlanState.initial(_decision(initial, search)).complete_next(search)
    current = state.current_plan

    with pytest.raises(PlanContractError, match="cannot claim"):
        state.apply_decision(_decision(current, finalize, replan=True))

    pretend_version = current.model_copy(update={"version": 2})
    with pytest.raises(PlanContractError, match="retain its version"):
        state.apply_decision(_decision(pretend_version, finalize))


def test_next_action_must_be_first_pending_and_completed_action_cannot_repeat() -> None:
    search = _search()
    excerpt = _excerpt()
    plan = _plan(1, (search, excerpt))
    state = PlanState.initial(_decision(plan, search))

    with pytest.raises(PlanContractError, match="first pending"):
        state.validate_next_action(excerpt)

    state = state.complete_next(search)
    with pytest.raises(PlanContractError, match="completed action"):
        state.apply_decision(_decision(_plan(2, (search,)), search))

    relabeled = search.model_copy(update={"reason_code": "SAME_ACTION_NEW_LABEL"})
    with pytest.raises(PlanContractError, match="completed action"):
        state.apply_decision(_decision(_plan(2, (relabeled,)), relabeled))


def test_completed_history_is_immutable_across_replan_and_exhaustion_is_explicit() -> None:
    search = _search()
    state = PlanState.initial(_decision(_plan(1, (search,)), search)).complete_next(search)
    history = state.completed_history
    rewrite = _search("different authorized search")
    replanned, changed = state.apply_decision(_decision(_plan(2, (rewrite,)), rewrite))

    assert changed is True
    assert replanned.completed_history == history
    assert replanned.completed_history[0].plan_version == 1

    exhausted = replanned.complete_next(rewrite)
    with pytest.raises(PlanExhaustedError):
        exhausted.validate_next_action(_finalize())
