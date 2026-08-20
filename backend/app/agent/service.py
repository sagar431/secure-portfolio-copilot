import logging
import time
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import AgentLoop
from app.agent.models import (
    AgentRunOutcome,
    StoppingReason,
    TerminalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.chat.repository import add_message, add_trace, get_owned_conversation
from app.chat.service import _home_tenant_id, _request_matches_scope
from app.core.errors import APIError
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.schemas.chat import AgentRunMessageData, AgentTraceEventData

logger = logging.getLogger("app.agent.audit")

_REFUSED = "I can't perform that request within your authorized scope."
_FAILED = "The agent could not complete the request safely."


class AgentRunService:
    def __init__(
        self,
        session: AsyncSession,
        loop: AgentLoop,
        gateway: ApprovedToolGateway,
        *,
        model_name: str,
    ) -> None:
        self._session = session
        self._loop = loop
        self._gateway = gateway
        self._model_name = model_name

    @staticmethod
    def _scope_denied_outcome() -> AgentRunOutcome:
        session_id = uuid4()
        return AgentRunOutcome(
            agent_session_id=session_id,
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

    @staticmethod
    def _failed_outcome() -> AgentRunOutcome:
        return AgentRunOutcome(
            agent_session_id=uuid4(),
            terminal_status=TerminalStatus.FAILED,
            stopping_reason=StoppingReason.TOOL_ERROR,
            answer=_FAILED,
            step_count=0,
            replan_count=0,
            retry_count=0,
            trace=(
                TraceEvent(
                    event_type=TraceEventType.TERMINAL,
                    status=TraceStatus.TERMINATED,
                    duration_ms=0,
                    reason_code="AGENT_FAILED_SAFE",
                ),
            ),
        )

    async def run(
        self,
        context: AuthorizationContext,
        *,
        conversation_id: UUID,
        question: str,
        request_id: str,
    ) -> AgentRunMessageData:
        started = time.monotonic()
        tenant_id = _home_tenant_id(context)
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

        user_message = await add_message(
            self._session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="user",
            content=question,
            request_id=request_id,
        )
        if not _request_matches_scope(context, question):
            outcome = self._scope_denied_outcome()
        else:
            permitted_tools = frozenset(
                item.value
                for item in self._gateway.authorized_catalog(context.scope, APPROVED_TOOL_NAMES)
            )
            try:
                outcome = await self._loop.run(
                    query=question,
                    authorization_context=context,
                    permitted_tools=permitted_tools,
                    request_id=request_id,
                )
            except Exception:
                outcome = self._failed_outcome()

        assistant_message = await add_message(
            self._session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="assistant",
            content=outcome.answer,
            request_id=request_id,
        )
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
            model_name=self._model_name,
            status=trace_status,
            reason_code=outcome.stopping_reason.value.upper(),
            document_ids=tuple(dict.fromkeys(item.document_id for item in outcome.citations)),
            chunk_ids=tuple(item.chunk_id for item in outcome.citations),
            input_tokens=None,
            output_tokens=None,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            retry_count=outcome.retry_count,
        )
        await self._session.commit()
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
            step_count=outcome.step_count,
            replan_count=outcome.replan_count,
            retry_count=outcome.retry_count,
            trace=tuple(
                AgentTraceEventData.model_validate(item.model_dump(mode="json"))
                for item in outcome.trace
            ),
        )
