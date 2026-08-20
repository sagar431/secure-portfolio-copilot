import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.agent.contracts import (
    AgentModelError,
    ApprovedToolGateway,
    DecisionProvider,
    GroundedFinalizer,
    PerceptionProvider,
)
from app.agent.models import (
    Action,
    ActionType,
    AgentLoopLimits,
    AgentRunOutcome,
    AgentSession,
    ObservationStatus,
    PerceptionSnapshot,
    Plan,
    Step,
    StepStatus,
    StoppingReason,
    StructuredObservation,
    TerminalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest, LLMProviderError
from app.chat.service import GroundingValidationError, validate_grounded_answer
from app.policies.models import AuthorizationContext
from app.schemas.chat import GroundedCitationData, GroundedClaimData

_T = TypeVar("_T")
_INSUFFICIENT = "I don't have sufficient authorized evidence to answer that question."
_REFUSED = "I can't perform that request within your authorized scope."
_CLARIFY = "Please clarify the document question you want answered."
_FAILED = "The agent could not complete the request safely."
_SEARCH_TOOL = "portfolio.search_authorized_documents"
_EXCERPT_TOOL = "portfolio.get_document_excerpt"
_TRACE_SAFE_TOOL_NAMES = frozenset({_SEARCH_TOOL, _EXCERPT_TOOL})


class AgentLoop:
    """Single owner of a bounded perceive-decide-act-observe request."""

    def __init__(
        self,
        *,
        perception: PerceptionProvider,
        decision: DecisionProvider,
        gateway: ApprovedToolGateway,
        finalizer: GroundedFinalizer,
        limits: AgentLoopLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._perception = perception
        self._decision = decision
        self._gateway = gateway
        self._finalizer = finalizer
        self._limits = limits or AgentLoopLimits()
        self._clock = clock

    async def _within_budget(self, awaitable: Awaitable[_T], *, started: float) -> _T:
        remaining = self._limits.max_duration_seconds - (self._clock() - started)
        if remaining <= 0:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await awaitable

    @staticmethod
    def _event(
        event_type: TraceEventType,
        status: TraceStatus,
        reason_code: str,
        *,
        action_name: str | None = None,
        duration_ms: int = 0,
        evidence_ids: tuple[str, ...] = (),
    ) -> TraceEvent:
        return TraceEvent(
            event_type=event_type,
            action_name=action_name if action_name in _TRACE_SAFE_TOOL_NAMES else None,
            status=status,
            duration_ms=max(0, duration_ms),
            evidence_reference_ids=evidence_ids,
            reason_code=reason_code,
        )

    @staticmethod
    def _action_matches_plan(action: Action, plan: Plan) -> bool:
        return any(
            step.status == StepStatus.PENDING
            and step.action_type == action.type
            and step.action_name == action.action_name
            for step in plan.steps
        )

    async def run(
        self,
        *,
        query: str,
        authorization_context: AuthorizationContext,
        permitted_tools: frozenset[str],
        request_id: str,
    ) -> AgentRunOutcome:
        started = self._clock()
        session = AgentSession(
            request_id=request_id,
            original_query=query,
            authorization_context=authorization_context,
            permitted_tools=permitted_tools,
        )
        trace: list[TraceEvent] = []
        perceptions: list[PerceptionSnapshot] = []
        plans: list[Plan] = []
        completed_steps: list[Step] = []
        observations: list[StructuredObservation] = []
        evidence_by_id: dict[str, GroundedEvidence] = {}
        step_count = replan_count = retry_count = 0
        retrieval_count = 0

        try:
            perception = await self._within_budget(
                self._perception.perceive_user_query(query=query), started=started
            )
        except TimeoutError:
            return self._terminal(
                session,
                TerminalStatus.LIMIT_REACHED,
                StoppingReason.MAX_DURATION,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        except AgentModelError:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.MODEL_ERROR,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        perceptions.append(perception)
        session = session.model_copy(update={"perceptions": tuple(perceptions)})
        trace.append(
            self._event(
                TraceEventType.PERCEPTION,
                TraceStatus.COMPLETED,
                "PERCEPTION_COMPLETED",
            )
        )
        trace.append(
            self._event(TraceEventType.POLICY, TraceStatus.COMPLETED, "TRUSTED_SCOPE_BOUND")
        )
        trace.append(
            self._event(
                TraceEventType.GATEWAY,
                TraceStatus.COMPLETED,
                "CAPABILITY_SHORTLIST_BOUND",
            )
        )

        try:
            decision = await self._within_budget(
                self._decision.decide_initial(
                    query=query,
                    perception=perception,
                    permitted_tools=permitted_tools,
                ),
                started=started,
            )
        except TimeoutError:
            return self._terminal(
                session,
                TerminalStatus.LIMIT_REACHED,
                StoppingReason.MAX_DURATION,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        except AgentModelError:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.MODEL_ERROR,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        plans.append(decision.plan)
        session = session.model_copy(update={"plans": tuple(plans)})

        while True:
            action = decision.next_action
            trace.append(
                self._event(
                    TraceEventType.DECISION,
                    TraceStatus.COMPLETED,
                    "DECISION_PRODUCED",
                    action_name=action.action_name,
                )
            )
            if decision.replan:
                replan_count += 1
                session = session.model_copy(update={"replan_count": replan_count})
                if replan_count > self._limits.max_replans:
                    return self._terminal(
                        session,
                        TerminalStatus.LIMIT_REACHED,
                        StoppingReason.MAX_REPLANS,
                        trace,
                        step_count,
                        replan_count,
                        retry_count,
                    )
            if not self._action_matches_plan(action, decision.plan):
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.PLAN_EXHAUSTED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )

            if action.type == ActionType.CLARIFY:
                return self._terminal(
                    session,
                    TerminalStatus.NEEDS_CLARIFICATION,
                    StoppingReason.CLARIFICATION_REQUIRED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                    answer=_CLARIFY,
                )
            if action.type == ActionType.REFUSE:
                return self._terminal(
                    session,
                    TerminalStatus.REFUSED,
                    StoppingReason.REQUEST_REFUSED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                    answer=_REFUSED,
                )
            if action.type == ActionType.FINALIZE:
                return await self._finalize(
                    session=session,
                    query=query,
                    evidence=tuple(evidence_by_id.values()),
                    started=started,
                    trace=trace,
                    step_count=step_count,
                    replan_count=replan_count,
                    retry_count=retry_count,
                )

            if step_count >= self._limits.max_steps:
                return self._terminal(
                    session,
                    TerminalStatus.LIMIT_REACHED,
                    StoppingReason.MAX_STEPS,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            if (
                action.action_name == _SEARCH_TOOL
                and retrieval_count >= 1 + self._limits.max_retrieval_rewrites
            ):
                return self._terminal(
                    session,
                    TerminalStatus.LIMIT_REACHED,
                    StoppingReason.MAX_RETRIEVAL_REWRITES,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            if action.action_name not in permitted_tools:
                trace.append(
                    self._event(
                        TraceEventType.GATEWAY,
                        TraceStatus.DENIED,
                        "TOOL_NOT_PERMITTED",
                        action_name=action.action_name,
                    )
                )
                return self._terminal(
                    session,
                    TerminalStatus.REFUSED,
                    StoppingReason.SCOPE_DENIED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                    answer=_REFUSED,
                )

            tool_started = self._clock()
            try:
                observation = await self._within_budget(
                    self._gateway.execute(
                        action=action,
                        authorization_context=authorization_context,
                        permitted_tools=permitted_tools,
                        request_id=request_id,
                    ),
                    started=started,
                )
            except TimeoutError:
                trace.append(
                    self._event(
                        TraceEventType.TOOL,
                        TraceStatus.TIMEOUT,
                        "TOOL_TIMEOUT",
                        action_name=action.action_name,
                    )
                )
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.TOOL_TIMEOUT,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            except Exception:
                trace.append(
                    self._event(
                        TraceEventType.TOOL,
                        TraceStatus.FAILED,
                        "TOOL_ERROR",
                        action_name=action.action_name,
                    )
                )
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.TOOL_ERROR,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )

            step_count += 1
            if action.action_name == _SEARCH_TOOL:
                retrieval_count += 1
            retry_count += observation.retry_count
            observations.append(observation)
            session = session.model_copy(
                update={
                    "step_count": step_count,
                    "retry_count": retry_count,
                    "observations": tuple(observations),
                }
            )
            trace.extend(
                (
                    self._event(
                        TraceEventType.GATEWAY,
                        TraceStatus.COMPLETED,
                        "ACTION_VALIDATED",
                        action_name=action.action_name,
                    ),
                    self._event(
                        TraceEventType.TOOL,
                        TraceStatus.COMPLETED
                        if observation.status == ObservationStatus.SUCCESS
                        else TraceStatus.DENIED
                        if observation.status == ObservationStatus.DENIED
                        else TraceStatus.TIMEOUT
                        if observation.status == ObservationStatus.TIMEOUT
                        else TraceStatus.FAILED,
                        observation.reason_code,
                        action_name=action.action_name,
                        duration_ms=int((self._clock() - tool_started) * 1000),
                        evidence_ids=observation.evidence_reference_ids,
                    ),
                    self._event(
                        TraceEventType.OBSERVATION,
                        TraceStatus.COMPLETED,
                        "OBSERVATION_VALIDATED",
                        action_name=action.action_name,
                        duration_ms=observation.duration_ms,
                        evidence_ids=observation.evidence_reference_ids,
                    ),
                )
            )
            if observation.status == ObservationStatus.DENIED:
                return self._terminal(
                    session,
                    TerminalStatus.REFUSED,
                    StoppingReason.SCOPE_DENIED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                    answer=_REFUSED,
                )
            if observation.status == ObservationStatus.TIMEOUT:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.TOOL_TIMEOUT,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            if observation.status == ObservationStatus.ERROR:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.TOOL_ERROR,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            for item in observation.evidence:
                evidence_by_id[item.evidence_id] = item
            matched_step = next(
                step
                for step in decision.plan.steps
                if step.status == StepStatus.PENDING
                and step.action_type == action.type
                and step.action_name == action.action_name
            )
            completed_steps.append(
                matched_step.model_copy(
                    update={"status": StepStatus.COMPLETED, "reason_code": "TOOL_COMPLETED"}
                )
            )
            session = session.model_copy(update={"completed_steps": tuple(completed_steps)})

            current_plan = decision.plan
            try:
                perception = await self._within_budget(
                    self._perception.perceive_step_result(
                        query=query, previous=perception, observation=observation
                    ),
                    started=started,
                )
                perceptions.append(perception)
                session = session.model_copy(update={"perceptions": tuple(perceptions)})
                trace.append(
                    self._event(
                        TraceEventType.PERCEPTION,
                        TraceStatus.COMPLETED,
                        "STEP_RESULT_PERCEIVED",
                        evidence_ids=observation.evidence_reference_ids,
                    )
                )
                decision = await self._within_budget(
                    self._decision.decide_mid_session(
                        query=query,
                        perception=perception,
                        current_plan=decision.plan,
                        completed_steps=tuple(completed_steps),
                        permitted_tools=permitted_tools,
                    ),
                    started=started,
                )
            except TimeoutError:
                return self._terminal(
                    session,
                    TerminalStatus.LIMIT_REACHED,
                    StoppingReason.MAX_DURATION,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            except AgentModelError:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.MODEL_ERROR,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            if decision.plan != current_plan and not decision.replan:
                decision = decision.model_copy(update={"replan": True})
            if decision.plan not in plans:
                plans.append(decision.plan)
                session = session.model_copy(update={"plans": tuple(plans)})

    async def _finalize(
        self,
        *,
        session: AgentSession,
        query: str,
        evidence: tuple[GroundedEvidence, ...],
        started: float,
        trace: list[TraceEvent],
        step_count: int,
        replan_count: int,
        retry_count: int,
    ) -> AgentRunOutcome:
        if not evidence:
            return self._terminal(
                session,
                TerminalStatus.INSUFFICIENT_EVIDENCE,
                StoppingReason.INSUFFICIENT_AUTHORIZED_EVIDENCE,
                trace,
                step_count,
                replan_count,
                retry_count,
                answer=_INSUFFICIENT,
            )
        trace.append(
            self._event(
                TraceEventType.FINALIZATION,
                TraceStatus.STARTED,
                "FINALIZATION_STARTED",
                evidence_ids=tuple(item.evidence_id for item in evidence),
            )
        )
        try:
            generation = await self._within_budget(
                self._finalizer.generate(
                    GroundedGenerationRequest(question=query, evidence=evidence)
                ),
                started=started,
            )
            validated = validate_grounded_answer(generation.answer, evidence)
        except TimeoutError:
            return self._terminal(
                session,
                TerminalStatus.LIMIT_REACHED,
                StoppingReason.MAX_DURATION,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        except LLMProviderError:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.MODEL_ERROR,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        except GroundingValidationError:
            return self._terminal(
                session,
                TerminalStatus.INSUFFICIENT_EVIDENCE,
                StoppingReason.CITATION_VALIDATION_FAILED,
                trace,
                step_count,
                replan_count,
                retry_count,
                answer=_INSUFFICIENT,
            )
        answer = " ".join(
            f"{claim.text} [{', '.join(claim.citation_ids)}]" for claim in validated.claims
        )
        trace.append(
            self._event(
                TraceEventType.FINALIZATION,
                TraceStatus.COMPLETED,
                "CITATIONS_VALIDATED",
                evidence_ids=tuple(item.citation_id for item in validated.citations),
            )
        )
        return self._terminal(
            session,
            TerminalStatus.COMPLETED,
            StoppingReason.COMPLETED,
            trace,
            step_count,
            replan_count,
            retry_count,
            answer=answer,
            claims=validated.claims,
            citations=validated.citations,
            limitations=validated.limitations,
        )

    def _terminal(
        self,
        session: AgentSession,
        status: TerminalStatus,
        reason: StoppingReason,
        trace: list[TraceEvent],
        step_count: int,
        replan_count: int,
        retry_count: int,
        *,
        answer: str = _FAILED,
        claims: tuple[GroundedClaimData, ...] = (),
        citations: tuple[GroundedCitationData, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> AgentRunOutcome:
        if status != TerminalStatus.COMPLETED and (claims or citations):
            raise ValueError("Only completed outcomes may carry claims or citations")
        terminal_trace_status = (
            TraceStatus.COMPLETED if status == TerminalStatus.COMPLETED else TraceStatus.TERMINATED
        )
        trace.append(
            self._event(TraceEventType.TERMINAL, terminal_trace_status, reason.value.upper())
        )
        session = session.model_copy(
            update={
                "terminal_status": status,
                "stopping_reason": reason,
                "step_count": step_count,
                "replan_count": replan_count,
                "retry_count": retry_count,
                "trace": tuple(trace),
            }
        )
        return AgentRunOutcome(
            agent_session_id=session.session_id,
            terminal_status=status,
            stopping_reason=reason,
            answer=answer,
            claims=claims,
            citations=citations,
            limitations=limitations,
            step_count=step_count,
            replan_count=replan_count,
            retry_count=retry_count,
            trace=tuple(trace),
        )
