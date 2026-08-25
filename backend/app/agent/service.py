import asyncio
import logging
import time
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.approval_repository import create_pending_approval
from app.agent.approval_security import authorization_scope_fingerprint
from app.agent.history_repository import (
    create_run,
    persist_checkpoint_history,
    persist_outcome_history,
    transition_run,
)
from app.agent.loop import (
    AgentLoop,
    ApprovalReconstructionMismatch,
    ApprovalRequired,
    ReconstructedStep,
)
from app.agent.models import (
    AgentRunOutcome,
    StoppingReason,
    TerminalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.chat.contracts import GroundedMemory, GroundedWorkingMessage
from app.chat.repository import (
    add_message,
    add_trace,
    get_owned_conversation,
    load_bounded_conversation_messages,
)
from app.chat.scope_guard import request_matches_authorized_scope, resolve_home_tenant_id
from app.core.errors import APIError
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.memory.contracts import CandidateAction, MemoryCandidate
from app.memory.service import MemoryService
from app.model_routing import ResponseMode, RoutingSignals, WorkloadKind, route_model
from app.models.agent_runs import AgentControlMode, AgentRun, AgentRunStatus
from app.models.chat import Message
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.schemas.agent_runs import (
    ApprovalStateData,
    AwaitingApprovalData,
    RemainingApprovalBudgetData,
)
from app.schemas.chat import (
    AgentRunMessageData,
    AgentTraceEventData,
    SafeAgentToolName,
    safe_model_name,
)

logger = logging.getLogger("app.agent.audit")

_REFUSED = "I can't perform that request within your authorized scope."
_ACTION_LABELS = {
    "portfolio.search_authorized_documents": "Search authorized documents",
    "portfolio.get_document_excerpt": "Read an authorized document excerpt",
    "portfolio.calculate_ebitda_margin": "Calculate EBITDA margin",
    "portfolio.calculate_revenue_growth": "Calculate revenue growth",
    "portfolio.calculate_net_profit_margin": "Calculate net profit margin",
    "portfolio.query_financial_metrics": "Query authorized financial metrics",
    "portfolio.calculate_debt_to_equity": "Calculate debt-to-equity",
    "portfolio.calculate_cash_runway": "Calculate cash runway",
    "portfolio.calculate_cagr": "Calculate CAGR",
    "portfolio.search_memory": "Search authorized private memory",
    "portfolio.propose_memory": "Propose a private memory",
}


class AgentRunService:
    def __init__(
        self,
        session: AsyncSession,
        loop: AgentLoop,
        gateway: ApprovedToolGateway,
        *,
        model_name: str,
        route_reason_code: str,
        low_confidence_threshold: float = 0.55,
        max_recent_messages: int = 8,
    ) -> None:
        self._session = session
        self._loop = loop
        self._gateway = gateway
        self._model_name = model_name
        self._route_reason_code = route_reason_code
        self._low_confidence_threshold = low_confidence_threshold
        self._max_recent_messages = max_recent_messages
        self._memory_service = MemoryService(session)

    async def _mark_run_terminal(
        self,
        run_id: UUID,
        *,
        status: AgentRunStatus,
        duration_ms: int,
        reason_code: str,
    ) -> None:
        await self._session.rollback()
        persisted_run = await self._session.get(AgentRun, run_id)
        if persisted_run is None:
            return
        if AgentRunStatus(persisted_run.status) not in {
            AgentRunStatus.CREATED,
            AgentRunStatus.RUNNING,
        }:
            return
        persisted_run.duration_ms = min(120_000, max(0, duration_ms))
        transition_run(persisted_run, status, reason_code=reason_code)
        await self._session.commit()

    @staticmethod
    def _scope_denied_outcome(run_id: UUID) -> AgentRunOutcome:
        return AgentRunOutcome(
            agent_session_id=run_id,
            terminal_status=TerminalStatus.REFUSED,
            stopping_reason=StoppingReason.SCOPE_DENIED,
            answer=_REFUSED,
            step_count=0,
            replan_count=0,
            retry_count=0,
            trace=(
                TraceEvent(
                    event_type=TraceEventType.POLICY,
                    status=TraceStatus.DENIED,
                    duration_ms=0,
                    reason_code="REQUEST_SCOPE_NOT_AUTHORIZED",
                ),
                TraceEvent(
                    event_type=TraceEventType.TERMINAL,
                    status=TraceStatus.TERMINATED,
                    duration_ms=0,
                    reason_code="SCOPE_DENIED",
                ),
            ),
        )

    async def run(
        self,
        context: AuthorizationContext,
        *,
        conversation_id: UUID,
        question: str,
        response_mode: ResponseMode = ResponseMode.AUTO,
        agent_control_mode: AgentControlMode = AgentControlMode.BALANCED,
        request_id: str,
        approved_action_hash: str | None = None,
        resume_run: AgentRun | None = None,
        reconstructed_steps: tuple[ReconstructedStep, ...] = (),
    ) -> AgentRunMessageData | AwaitingApprovalData:
        started = time.monotonic()
        tenant_id = resolve_home_tenant_id(context)
        conversation = await get_owned_conversation(
            self._session,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        if conversation is None:
            raise APIError(404, "not_found", "Conversation was not found.")
        if not any(
            Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants
        ):
            raise APIError(403, "forbidden", "Agent document access is not permitted.")

        run_id = resume_run.id if resume_run is not None else uuid4()
        route_reason_code = "NO_MODEL_CALL"
        resolved_response_mode: ResponseMode | None = None
        request_scope_allowed = request_matches_authorized_scope(context, question)
        recent_messages: tuple[GroundedWorkingMessage, ...] = ()
        conversation_summary: str | None = None
        if request_scope_allowed:
            routing_decision = route_model(
                RoutingSignals(WorkloadKind.AGENTIC, question, 0, None),
                low_confidence_threshold=self._low_confidence_threshold,
                response_mode=response_mode,
            )
            if routing_decision.upgrade_required:
                raise APIError(
                    409,
                    "deep_mode_required",
                    "This request requires broader analysis.",
                )
            route_reason_code = routing_decision.reason.value
            resolved_response_mode = routing_decision.resolved_response_mode
            recent_rows = await load_bounded_conversation_messages(
                self._session,
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                user_id=context.identity.user_id,
                limit=self._max_recent_messages + 1,
            )
            if resume_run is not None and resume_run.initial_user_message_id is not None:
                recent_rows = tuple(
                    item for item in recent_rows if item.id != resume_run.initial_user_message_id
                )
            recent_messages = tuple(
                GroundedWorkingMessage(role=item.role, content=item.content[:500])  # type: ignore[arg-type]
                for item in recent_rows[-self._max_recent_messages :]
            )
            conversation_summary = await self._memory_service.get_conversation_summary(
                context, conversation_id=conversation.id
            )

        if resume_run is None:
            run_record = await create_run(
                self._session,
                run_id=run_id,
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                user_id=context.identity.user_id,
                response_mode=response_mode.value,
                agent_control_mode=agent_control_mode.value,
                selected_model_tier=(
                    resolved_response_mode.value if resolved_response_mode is not None else None
                ),
                selected_model_name=(
                    safe_model_name(self._model_name)
                    if resolved_response_mode is not None
                    else None
                ),
                policy_decision="ALLOWED" if request_scope_allowed else "DENIED",
                policy_reason_code=(
                    "REQUEST_SCOPE_AUTHORIZED"
                    if request_scope_allowed
                    else "REQUEST_SCOPE_NOT_AUTHORIZED"
                ),
            )
            if request_scope_allowed:
                transition_run(
                    run_record, AgentRunStatus.RUNNING, reason_code="AGENT_EXECUTION_STARTED"
                )
            await self._session.commit()
        else:
            run_record = resume_run
            if AgentRunStatus(run_record.status) is not AgentRunStatus.RUNNING:
                raise APIError(404, "not_found", "Agent run was not found.")

        try:
            if resume_run is not None:
                if run_record.initial_user_message_id is None:
                    raise ValueError("Missing immutable initial message reference")
                user_message = await self._session.get(Message, run_record.initial_user_message_id)
                if user_message is None or user_message.content != question:
                    raise ValueError("Initial message reconstruction failed")
            elif not request_scope_allowed:
                user_message = await add_message(
                    self._session,
                    conversation=conversation,
                    user_id=context.identity.user_id,
                    role="user",
                    content=question,
                    request_id=request_id,
                )
                outcome = self._scope_denied_outcome(run_id)
            else:
                user_message = await add_message(
                    self._session,
                    conversation=conversation,
                    user_id=context.identity.user_id,
                    role="user",
                    content=question,
                    request_id=request_id,
                )
            if resume_run is None:
                run_record.initial_user_message_id = user_message.id
                await self._session.flush()
            if not request_scope_allowed:
                outcome = self._scope_denied_outcome(run_id)
            else:
                permitted_tool_catalog = self._gateway.permitted_catalog(
                    context.scope, APPROVED_TOOL_NAMES
                )
                memory_rows = await self._memory_service.retrieve_relevant(
                    context,
                    query=question,
                    semantic_limit=3,
                    episodic_limit=2,
                )
                memories = tuple(
                    GroundedMemory(
                        memory_id=item.id,
                        scope=item.scope,
                        memory_type=item.memory_type,
                        content=item.content[:500],
                    )
                    for item in memory_rows[:5]
                )
                outcome = await self._loop.run(
                    query=question,
                    authorization_context=context,
                    permitted_tool_catalog=permitted_tool_catalog,
                    request_id=request_id,
                    agent_run_id=run_id,
                    agent_control_mode=agent_control_mode,
                    approved_action_hash=approved_action_hash,
                    reconstructed_steps=reconstructed_steps,
                    memories=memories,
                    recent_messages=recent_messages,
                    conversation_summary=conversation_summary,
                )
                if outcome.memory_proposal is not None:
                    company_ids = {
                        company_id
                        for grant in context.scope.grants
                        if Capability.QUERY_DOCUMENTS in grant.capabilities
                        for company_id in grant.company_ids
                    }
                    notifications: tuple[str, ...] = ()
                    if len(company_ids) == 1:
                        proposal = outcome.memory_proposal
                        notifications = await self._memory_service.apply_semantic_candidates(
                            context,
                            candidates=(
                                MemoryCandidate(
                                    memory_type=proposal.memory_type,
                                    action=CandidateAction.ADD,
                                    content=proposal.content,
                                    normalized_key=proposal.normalized_key,
                                    confidence=1.0 if proposal.explicit else 0.7,
                                    importance=0.7,
                                    sensitivity="LOW",
                                    reason="Agent proposal accepted by host memory policy",
                                    explicit=proposal.explicit,
                                ),
                            ),
                            company_id=next(iter(company_ids)),
                            conversation_id=conversation.id,
                            source_message_id=user_message.id,
                        )
                    outcome = outcome.model_copy(
                        update={
                            "answer": (
                                notifications[0]
                                if notifications
                                else "The host memory policy rejected that proposal."
                            )
                        }
                    )
            assistant_message = await add_message(
                self._session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="assistant",
                content=outcome.answer,
                request_id=request_id,
            )
        except ApprovalReconstructionMismatch:
            await self._mark_run_terminal(
                run_id,
                status=AgentRunStatus.FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                reason_code="APPROVED_ACTION_HASH_MISMATCH",
            )
            raise APIError(
                409,
                "approval_mismatch",
                "The approved action could not be reconstructed safely.",
            ) from None
        except ApprovalRequired as pending:
            from app.agent.models import Action, Plan

            action = pending.action
            if not isinstance(action, Action) or action.action_name is None:
                await self._mark_run_terminal(
                    run_id,
                    status=AgentRunStatus.FAILED,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    reason_code="APPROVAL_RECONSTRUCTION_INVALID",
                )
                raise APIError(
                    500, "agent_run_failed", "The agent could not pause safely."
                ) from None
            plans = tuple(item for item in pending.plans if isinstance(item, Plan))
            if len(plans) != len(pending.plans):
                raise APIError(
                    500, "agent_run_failed", "The agent could not pause safely."
                ) from None
            await persist_checkpoint_history(
                self._session,
                run=run_record,
                scope=context.scope,
                plans=plans,
                safe_steps=pending.safe_steps,
                safe_observations=pending.safe_observations,
            )
            approval = await create_pending_approval(
                self._session,
                run=run_record,
                plans=plans,
                plan_version=pending.plan_version,
                proposed_step_number=pending.proposed_step_number,
                tool_name=action.action_name,
                action_hash=pending.action_hash,
                scope_fingerprint=authorization_scope_fingerprint(context.scope),
                risk_class=pending.risk_class,
            )
            run_record.perception_status = "COMPLETED"
            run_record.perception_reason_code = "PERCEPTION_COMPLETED"
            transition_run(
                run_record,
                AgentRunStatus.AWAITING_APPROVAL,
                reason_code="USER_APPROVAL_REQUIRED",
            )
            await self._session.commit()
            grant = context.scope.grants[0]
            scope_summary = f"{grant.workspace_name} · {grant.primary_department.title()}"
            if user_message is None:
                raise APIError(
                    500, "agent_run_failed", "The agent could not pause safely."
                ) from None
            return AwaitingApprovalData(
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                agent_session_id=run_id,
                agent_control_mode=agent_control_mode,
                approval=ApprovalStateData(
                    approval_id=approval.id,
                    run_id=run_id,
                    status="PENDING",
                    action_label=_ACTION_LABELS[action.action_name],
                    safe_explanation=(
                        "Use an allow-listed tool within your current authorized scope."
                    ),
                    tool_name=action.action_name,
                    risk_level=pending.risk_class,
                    resource_type=(
                        "authorized private memory"
                        if action.action_name
                        in {
                            "portfolio.search_memory",
                            "portfolio.propose_memory",
                        }
                        else "authorized financial data"
                        if ".calculate_" in action.action_name
                        or action.action_name == "portfolio.query_financial_metrics"
                        else "authorized portfolio documents"
                    ),
                    estimated_cost_class="low",
                    safe_scope_summary=scope_summary,
                    remaining_budget=RemainingApprovalBudgetData(
                        steps=pending.remaining_tools,
                        tools=pending.remaining_tools,
                    ),
                    expires_at=approval.expires_at,
                ),
            )
        except asyncio.CancelledError:
            await self._mark_run_terminal(
                run_id,
                status=AgentRunStatus.CANCELLED,
                duration_ms=int((time.monotonic() - started) * 1000),
                reason_code="REQUEST_CANCELLED",
            )
            raise
        except Exception:
            await self._mark_run_terminal(
                run_id,
                status=AgentRunStatus.FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                reason_code="AGENT_EXECUTION_FAILED_SAFE",
            )
            raise APIError(
                500,
                "agent_run_failed",
                "The agent could not complete the request safely.",
            ) from None
        trace_status = (
            "grounded"
            if outcome.terminal_status == TerminalStatus.COMPLETED
            else "provider_error"
            if outcome.stopping_reason in {StoppingReason.MODEL_ERROR, StoppingReason.TOOL_ERROR}
            else "insufficient_evidence"
        )
        add_trace(
            self._session,
            request_id=request_id,
            conversation=conversation,
            user_id=context.identity.user_id,
            model_name=(
                self._model_name if route_reason_code != "NO_MODEL_CALL" else "NO_MODEL_CALL"
            ),
            status=trace_status,
            reason_code=outcome.stopping_reason.value.upper(),
            intent_route="AGENT",
            document_ids=tuple(dict.fromkeys(item.document_id for item in outcome.citations)),
            chunk_ids=tuple(item.chunk_id for item in outcome.citations),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            retry_count=outcome.retry_count,
            route_reason_code=route_reason_code,
        )
        duration_ms = min(120_000, max(0, int((time.monotonic() - started) * 1000)))
        run_record.duration_ms = duration_ms
        run_record.final_assistant_message_id = assistant_message.id
        run_record.perception_status, run_record.perception_reason_code = (
            ("COMPLETED", "PERCEPTION_COMPLETED")
            if any(item.event_type == TraceEventType.PERCEPTION for item in outcome.trace)
            else ("FAILED", "PERCEPTION_MODEL_FAILED")
            if outcome.stopping_reason == StoppingReason.MODEL_ERROR and request_scope_allowed
            else ("NOT_STARTED", "PERCEPTION_NOT_STARTED")
        )
        terminal_status = {
            TerminalStatus.COMPLETED: AgentRunStatus.COMPLETED,
            TerminalStatus.REFUSED: AgentRunStatus.REFUSED,
            TerminalStatus.NEEDS_CLARIFICATION: AgentRunStatus.CLARIFICATION_REQUIRED,
            TerminalStatus.INSUFFICIENT_EVIDENCE: AgentRunStatus.INSUFFICIENT_EVIDENCE,
            TerminalStatus.LIMIT_REACHED: AgentRunStatus.LIMIT_REACHED,
            TerminalStatus.FAILED: AgentRunStatus.FAILED,
        }[outcome.terminal_status]
        try:
            await persist_outcome_history(
                self._session,
                run=run_record,
                scope=context.scope,
                outcome=outcome,
            )
            transition_run(
                run_record,
                terminal_status,
                reason_code=outcome.stopping_reason.value.upper(),
            )
            await self._session.commit()
        except asyncio.CancelledError:
            await self._mark_run_terminal(
                run_id,
                status=AgentRunStatus.CANCELLED,
                duration_ms=duration_ms,
                reason_code="REQUEST_CANCELLED",
            )
            raise
        except Exception:
            await self._mark_run_terminal(
                run_id,
                status=AgentRunStatus.FAILED,
                duration_ms=duration_ms,
                reason_code="PERSISTENCE_VALIDATION_FAILED",
            )
            raise APIError(
                500,
                "agent_history_failed",
                "The agent run could not be recorded safely.",
            ) from None
        logger.info(
            "agent_run_event",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation.id),
                "agent_session_id": str(outcome.agent_session_id),
                "status": outcome.terminal_status.value,
                "reason_code": outcome.stopping_reason.value.upper(),
                "step_count": outcome.step_count,
                "replan_count": outcome.replan_count,
                "retry_count": outcome.retry_count,
                "citation_count": len(outcome.citations),
            },
        )
        return AgentRunMessageData(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            agent_session_id=outcome.agent_session_id,
            terminal_status=outcome.terminal_status.value,
            stopping_reason=outcome.stopping_reason.value,
            answer=outcome.answer,
            claims=outcome.claims,
            citations=outcome.citations,
            limitations=outcome.limitations,
            calculations=outcome.calculations,
            step_count=outcome.step_count,
            replan_count=outcome.replan_count,
            retry_count=outcome.retry_count,
            selected_intent=(outcome.selected_intent.value if outcome.selected_intent else None),
            policy_decision=outcome.policy_decision,
            tool_shortlist=cast(tuple[SafeAgentToolName, ...], outcome.tool_shortlist),
            plan_version=outcome.plan_version,
            evidence_advanced_goal=outcome.evidence_advanced_goal,
            trace=tuple(
                AgentTraceEventData.model_validate(item.model_dump(mode="json"))
                for item in outcome.trace
            ),
            model_name=(
                safe_model_name(self._model_name) if route_reason_code != "NO_MODEL_CALL" else None
            ),
            route_reason=(route_reason_code if route_reason_code != "NO_MODEL_CALL" else None),
            requested_response_mode=response_mode,
            resolved_response_mode=resolved_response_mode,
        )
