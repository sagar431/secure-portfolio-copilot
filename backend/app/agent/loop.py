import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID, uuid4

from app.agent.approval_security import canonical_action_hash, classify_tool_risk
from app.agent.contracts import (
    AgentModelError,
    ApprovedToolGateway,
    DecisionProvider,
    GroundedFinalizer,
    PerceptionProvider,
)
from app.agent.models import (
    ActionType,
    AgentLoopLimits,
    AgentRunOutcome,
    AgentSession,
    ObservationStatus,
    PerceptionSnapshot,
    RemainingBudgets,
    SafeObservationSnapshot,
    SafeStepSnapshot,
    StoppingReason,
    StructuredObservation,
    TerminalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.agent.plan_state import PlanContractError, PlanExhaustedError, PlanState
from app.calculations.contracts import CalculationMetric, CalculationResult
from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest, LLMProviderError
from app.chat.service import GroundingValidationError, validate_grounded_answer
from app.mcp_gateway.contracts import PermittedToolDescriptor
from app.models.agent_runs import AgentControlMode, ApprovalRiskClass
from app.policies.models import AuthorizationContext
from app.schemas.chat import (
    CalculationData,
    CalculationInputData,
    GroundedCitationData,
    GroundedClaimData,
)

_T = TypeVar("_T")
_INSUFFICIENT = "I don't have sufficient authorized evidence to answer that question."
_REFUSED = "I can't perform that request within your authorized scope."
_CLARIFY = "Please clarify the document question you want answered."
_FAILED = "The agent could not complete the request safely."
_SEARCH_TOOL = "portfolio.search_authorized_documents"
_EXCERPT_TOOL = "portfolio.get_document_excerpt"
_CALCULATOR_TOOLS = frozenset(
    {
        "portfolio.calculate_ebitda_margin",
        "portfolio.calculate_revenue_growth",
        "portfolio.calculate_net_profit_margin",
    }
)
_TRACE_SAFE_TOOL_NAMES = frozenset({_SEARCH_TOOL, _EXCERPT_TOOL, *_CALCULATOR_TOOLS})


@dataclass(frozen=True, slots=True)
class ApprovalRequired(Exception):
    action: object
    action_hash: str
    plan_version: int
    proposed_step_number: int
    plans: tuple[object, ...]
    step_count: int
    remaining_tools: int
    risk_class: ApprovalRiskClass
    safe_steps: tuple[SafeStepSnapshot, ...]
    safe_observations: tuple[SafeObservationSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ReconstructedStep:
    action_hash: str
    observation: StructuredObservation


class ApprovalReconstructionMismatch(Exception):
    pass


def _must_pause(
    mode: AgentControlMode, risk: ApprovalRiskClass, action_hash: str, approved_hash: str | None
) -> bool:
    if approved_hash == action_hash:
        return False
    if risk is ApprovalRiskClass.ALWAYS_REQUIRE_APPROVAL:
        return True
    return mode is AgentControlMode.GUIDED


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

    async def run(
        self,
        *,
        query: str,
        authorization_context: AuthorizationContext,
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
        request_id: str,
        agent_run_id: UUID | None = None,
        agent_control_mode: AgentControlMode = AgentControlMode.BALANCED,
        approved_action_hash: str | None = None,
        reconstructed_steps: tuple[ReconstructedStep, ...] = (),
    ) -> AgentRunOutcome:
        started = self._clock()
        session = AgentSession(
            session_id=agent_run_id or uuid4(),
            request_id=request_id,
            original_query=query,
            authorization_context=authorization_context,
            permitted_tool_catalog=permitted_tool_catalog,
        )
        permitted_tools = frozenset(item.name.value for item in permitted_tool_catalog)
        trace: list[TraceEvent] = []
        perceptions: list[PerceptionSnapshot] = []
        observations: list[StructuredObservation] = []
        evidence_by_id: dict[str, GroundedEvidence] = {}
        step_count = replan_count = retry_count = 0
        retrieval_count = 0
        reconstructed_index = 0
        if reconstructed_steps:
            self._gateway.set_evidence_sequence(
                sum(len(item.observation.evidence) for item in reconstructed_steps)
            )

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
                    permitted_tool_catalog=permitted_tool_catalog,
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
        try:
            plan_state = PlanState.initial(decision)
        except PlanExhaustedError:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.PLAN_EXHAUSTED,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        except PlanContractError:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.MALFORMED_ACTION,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        session = session.model_copy(update={"plans": plan_state.versions})

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
            try:
                active_plan_step = plan_state.validate_next_action(action)
            except PlanExhaustedError:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.PLAN_EXHAUSTED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            except PlanContractError:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.MALFORMED_ACTION,
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

            assert action.action_name is not None
            tool_name = action.action_name
            risk_class = classify_tool_risk(tool_name)
            action_hash = canonical_action_hash(action)
            tool_started = self._clock()
            if reconstructed_index < len(reconstructed_steps):
                reconstructed = reconstructed_steps[reconstructed_index]
                if reconstructed.action_hash != action_hash:
                    raise ApprovalReconstructionMismatch
                observation = reconstructed.observation
                reconstructed_index += 1
            else:
                if approved_action_hash is not None and approved_action_hash != action_hash:
                    raise ApprovalReconstructionMismatch
                if _must_pause(agent_control_mode, risk_class, action_hash, approved_action_hash):
                    raise ApprovalRequired(
                        action=action,
                        action_hash=action_hash,
                        plan_version=plan_state.current_plan.version,
                        proposed_step_number=step_count + 1,
                        plans=tuple(plan_state.versions),
                        step_count=step_count,
                        remaining_tools=max(0, self._limits.max_steps - step_count),
                        risk_class=risk_class,
                        safe_steps=session.safe_steps,
                        safe_observations=session.safe_observations,
                    )
                # An approval is for exactly one action, not a blanket continuation.
                if approved_action_hash == action_hash:
                    approved_action_hash = None
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
                    tool_duration_ms = max(0, int((self._clock() - tool_started) * 1000))
                    session = session.model_copy(
                        update={
                            "safe_steps": session.safe_steps
                            + (
                                SafeStepSnapshot(
                                    plan_version=plan_state.current_plan.version,
                                    plan_step_index=active_plan_step.step_index,
                                    tool_name=tool_name,
                                    action_argument_hash=action_hash,
                                    status="TIMEOUT",
                                    policy_decision="ALLOWED",
                                    reason_code="TOOL_TIMEOUT",
                                    duration_ms=tool_duration_ms,
                                ),
                            )
                        }
                    )
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
                    tool_duration_ms = max(0, int((self._clock() - tool_started) * 1000))
                    session = session.model_copy(
                        update={
                            "safe_steps": session.safe_steps
                            + (
                                SafeStepSnapshot(
                                    plan_version=plan_state.current_plan.version,
                                    plan_step_index=active_plan_step.step_index,
                                    tool_name=tool_name,
                                    action_argument_hash=action_hash,
                                    status="FAILED",
                                    policy_decision="ALLOWED",
                                    reason_code="TOOL_ERROR",
                                    duration_ms=tool_duration_ms,
                                ),
                            )
                        }
                    )
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
            tool_duration_ms = max(0, int((self._clock() - tool_started) * 1000))
            safe_step = SafeStepSnapshot(
                plan_version=plan_state.current_plan.version,
                plan_step_index=active_plan_step.step_index,
                tool_name=tool_name,
                action_argument_hash=action_hash,
                status=(
                    "COMPLETED"
                    if observation.status == ObservationStatus.SUCCESS
                    else "DENIED"
                    if observation.status == ObservationStatus.DENIED
                    else "TIMEOUT"
                    if observation.status == ObservationStatus.TIMEOUT
                    else "FAILED"
                ),
                policy_decision=(
                    "DENIED" if observation.status == ObservationStatus.DENIED else "ALLOWED"
                ),
                reason_code=observation.reason_code,
                duration_ms=tool_duration_ms,
            )
            safe_observation = SafeObservationSnapshot.model_validate(
                {
                    "status": observation.status.value.upper(),
                    "reason_code": observation.reason_code,
                    "document_ids": tuple(item.document_id for item in observation.evidence),
                    "chunk_ids": tuple(item.chunk_id for item in observation.evidence),
                    "citation_ids": tuple(item.evidence_id for item in observation.evidence),
                    "retry_count": observation.retry_count,
                    "duration_ms": observation.duration_ms,
                }
            )
            session = session.model_copy(
                update={
                    "step_count": step_count,
                    "retry_count": retry_count,
                    "observations": tuple(observations),
                    "safe_steps": session.safe_steps + (safe_step,),
                    "safe_observations": session.safe_observations + (safe_observation,),
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
                        duration_ms=tool_duration_ms,
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
            plan_state = plan_state.complete_next(action)
            session = session.model_copy(
                update={
                    "plans": plan_state.versions,
                    "completed_steps": plan_state.completed_history,
                }
            )
            if observation.calculations:
                return self._finalize_calculations(
                    session=session,
                    calculations=observation.calculations,
                    evidence=observation.evidence,
                    trace=trace,
                    step_count=step_count,
                    replan_count=replan_count,
                    retry_count=retry_count,
                )
            remaining_budgets = RemainingBudgets(
                tool_steps=max(0, self._limits.max_steps - step_count),
                retrieval_rewrites=max(
                    0,
                    self._limits.max_retrieval_rewrites - max(0, retrieval_count - 1),
                ),
                replans=max(0, self._limits.max_replans - replan_count),
                latest_tool_retries=max(0, 1 - observation.retry_count),
                duration_ms=max(
                    0,
                    int((self._limits.max_duration_seconds - (self._clock() - started)) * 1000),
                ),
            )
            try:
                perception = await self._within_budget(
                    self._perception.perceive_step_result(
                        query=query,
                        previous=perception,
                        current_plan=plan_state.current_plan,
                        completed_steps=plan_state.completed_history,
                        observation=observation,
                        remaining_budgets=remaining_budgets,
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
                        current_plan=plan_state.current_plan,
                        completed_steps=plan_state.completed_history,
                        permitted_tool_catalog=permitted_tool_catalog,
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
            try:
                plan_state, changed = plan_state.apply_decision(decision)
            except PlanExhaustedError:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.PLAN_EXHAUSTED,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            except PlanContractError:
                return self._terminal(
                    session,
                    TerminalStatus.FAILED,
                    StoppingReason.MALFORMED_ACTION,
                    trace,
                    step_count,
                    replan_count,
                    retry_count,
                )
            if changed:
                replan_count += 1
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
            session = session.model_copy(
                update={"plans": plan_state.versions, "replan_count": replan_count}
            )

    def _finalize_calculations(
        self,
        *,
        session: AgentSession,
        calculations: tuple[CalculationResult, ...],
        evidence: tuple[GroundedEvidence, ...],
        trace: list[TraceEvent],
        step_count: int,
        replan_count: int,
        retry_count: int,
    ) -> AgentRunOutcome:
        if len(calculations) != 1:
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.TOOL_ERROR,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        calculation = calculations[0]
        if len(evidence) != len(calculation.trusted_inputs):
            return self._terminal(
                session,
                TerminalStatus.FAILED,
                StoppingReason.TOOL_ERROR,
                trace,
                step_count,
                replan_count,
                retry_count,
            )
        citation_ids = tuple(item.evidence_id for item in evidence)
        citations = tuple(
            GroundedCitationData(
                citation_id=item.evidence_id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                chunk_id=item.chunk_id,
                document_title=item.document_title,
                version_number=item.version_number,
                excerpt=item.excerpt,
                page_number=item.page_number,
                sheet_name=item.sheet_name,
                row_start=item.row_start,
                row_end=item.row_end,
                cell_start=item.cell_start,
                cell_end=item.cell_end,
            )
            for item in evidence
        )
        metric_label = {
            CalculationMetric.EBITDA_MARGIN: "EBITDA margin",
            CalculationMetric.REVENUE_GROWTH: "Revenue growth",
            CalculationMetric.NET_PROFIT_MARGIN: "Net profit margin",
        }[calculation.metric]
        claim_text = (
            f"{metric_label} for {calculation.company_slug} in {calculation.period} "
            f"is {calculation.result:.2f}%."
        )
        calculation_data = CalculationData(
            calculation_id=calculation.calculation_id,
            metric=calculation.metric.value,
            company_slug=calculation.company_slug,
            period=calculation.period,
            formula=calculation.formula,
            trusted_inputs=tuple(
                CalculationInputData(
                    name=trusted.name,
                    period=trusted.period,
                    value=trusted.value,
                    unit=trusted.unit,
                    citation_id=source.evidence_id,
                )
                for trusted, source in zip(calculation.trusted_inputs, evidence, strict=True)
            ),
            result=calculation.result,
            unit=calculation.unit,
            citation_ids=citation_ids,
        )
        trace.append(
            self._event(
                TraceEventType.FINALIZATION,
                TraceStatus.COMPLETED,
                "DETERMINISTIC_CALCULATION_VALIDATED",
                evidence_ids=citation_ids,
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
            answer=" ".join(
                f"{claim_text} [{', '.join(citation_ids)}] Formula: {calculation.formula}.".split()
            ),
            claims=(GroundedClaimData(text=claim_text, citation_ids=citation_ids),),
            citations=citations,
            calculations=(calculation_data,),
        )

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
            input_tokens=generation.usage.input_tokens,
            output_tokens=generation.usage.output_tokens,
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
        calculations: tuple[CalculationData, ...] = (),
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> AgentRunOutcome:
        if status != TerminalStatus.COMPLETED and (claims or citations or calculations):
            raise ValueError("Only completed outcomes may carry claims, citations, or calculations")
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
            calculations=calculations,
            step_count=step_count,
            replan_count=replan_count,
            retry_count=retry_count,
            trace=tuple(trace),
            plan_versions=session.plans,
            safe_steps=session.safe_steps,
            safe_observations=session.safe_observations,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
