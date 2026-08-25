from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.approval_security import authorization_scope_fingerprint
from app.agent.history_repository import transition_run
from app.agent.loop import ReconstructedStep
from app.agent.models import ObservationStatus, StructuredObservation
from app.agent.service import AgentRunService
from app.chat.contracts import GroundedEvidence
from app.chat.scope_guard import resolve_home_tenant_id
from app.core.errors import APIError
from app.mcp_gateway.adapters import GetDocumentExcerptAdapter
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES, GetDocumentExcerptInput, ToolPayload
from app.model_routing import ResponseMode
from app.models.agent_runs import (
    AgentApprovalRequest,
    AgentControlMode,
    AgentPlanVersion,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    ApprovalStatus,
)
from app.models.chat import Message
from app.policies.models import AuthorizationContext
from app.schemas.agent_runs import (
    ApprovalStateData,
    AwaitingApprovalData,
    RemainingApprovalBudgetData,
    SafelyTerminatedData,
)
from app.schemas.chat import AgentRunMessageData


class AgentApprovalService:
    def __init__(self, session: AsyncSession, runner: AgentRunService) -> None:
        self._session = session
        self._runner = runner

    async def _reconstruct_completed_steps(
        self, context: AuthorizationContext, *, run_id: UUID
    ) -> tuple[ReconstructedStep, ...]:
        steps = tuple(
            (
                await self._session.scalars(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id)
                    .order_by(AgentStep.step_number)
                    .options(selectinload(AgentStep.observation))
                )
            ).all()
        )
        adapter = GetDocumentExcerptAdapter(self._session)
        reconstructed: list[ReconstructedStep] = []
        for step in steps:
            record = step.observation
            if record is None or record.status != "SUCCESS":
                raise APIError(409, "resume_failed", "The run could not be resumed safely.")
            if step.tool_name.startswith("portfolio.calculate_"):
                raise APIError(409, "resume_failed", "The run could not be resumed safely.")
            evidence: list[GroundedEvidence] = []
            for document_id, chunk_id, citation_id in zip(
                record.authorized_document_ids,
                record.authorized_chunk_ids,
                record.citation_ids,
                strict=True,
            ):
                payload = await adapter.invoke(
                    arguments=GetDocumentExcerptInput(
                        document_id=UUID(document_id), chunk_id=UUID(chunk_id)
                    ),
                    authorization_scope=context.scope,
                    request_id="approval-reconstruction",
                )
                if not isinstance(payload, ToolPayload) or len(payload.evidence) != 1:
                    raise APIError(409, "resume_failed", "The run could not be resumed safely.")
                item = payload.evidence[0]
                evidence.append(
                    GroundedEvidence(
                        evidence_id=citation_id,
                        chunk_id=item.chunk_id,
                        document_id=item.document_id,
                        document_version_id=item.document_version_id,
                        version_number=item.version_number,
                        document_title=item.document_title,
                        excerpt=item.excerpt,
                        page_number=item.location.page_number,
                        sheet_name=item.location.sheet_name,
                        row_start=item.location.row_start,
                        row_end=item.location.row_end,
                        cell_start=item.location.cell_start,
                        cell_end=item.location.cell_end,
                    )
                )
            reconstructed.append(
                ReconstructedStep(
                    action_hash=step.action_argument_hash,
                    observation=StructuredObservation(
                        tool_name=step.tool_name,
                        status=ObservationStatus.SUCCESS,
                        evidence=tuple(evidence),
                        duration_ms=record.duration_ms,
                        retry_count=record.retry_count,
                        reason_code=record.safe_reason_code,
                    ),
                )
            )
        return tuple(reconstructed)

    async def _locked_owned(
        self, context: AuthorizationContext, *, run_id: UUID, approval_id: UUID
    ) -> tuple[AgentRun, AgentApprovalRequest]:
        tenant_id = resolve_home_tenant_id(context)
        row = (
            await self._session.execute(
                select(AgentRun, AgentApprovalRequest)
                .join(AgentApprovalRequest, AgentApprovalRequest.run_id == AgentRun.id)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.user_id == context.identity.user_id,
                    AgentApprovalRequest.id == approval_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise APIError(404, "not_found", "Agent run was not found.")
        return row[0], row[1]

    async def _binding_is_current(self, run: AgentRun, approval: AgentApprovalRequest) -> bool:
        latest_plan_version = await self._session.scalar(
            select(func.max(AgentPlanVersion.version)).where(AgentPlanVersion.run_id == run.id)
        )
        persisted_step_count = await self._session.scalar(
            select(func.count()).select_from(AgentStep).where(AgentStep.run_id == run.id)
        )
        return bool(
            latest_plan_version is not None
            and approval.plan_version == latest_plan_version
            and run.plan_version_count == latest_plan_version
            and approval.proposed_step_number == (persisted_step_count or 0) + 1
            and approval.action_name == approval.tool_name
            and approval.tool_name in APPROVED_TOOL_NAMES
        )

    async def approve_once(
        self,
        context: AuthorizationContext,
        *,
        run_id: UUID,
        approval_id: UUID,
        request_id: str,
    ) -> AgentRunMessageData | AwaitingApprovalData:
        run, approval = await self._locked_owned(context, run_id=run_id, approval_id=approval_id)
        now = datetime.now(UTC)
        if (
            approval.status != ApprovalStatus.PENDING.value
            or run.status != AgentRunStatus.AWAITING_APPROVAL.value
        ):
            raise APIError(409, "approval_unavailable", "This approval is no longer available.")
        if approval.expires_at <= now:
            approval.status = ApprovalStatus.EXPIRED.value
            approval.resolved_at = now
            approval.resolver_user_id = context.identity.user_id
            transition_run(run, AgentRunStatus.FAILED, reason_code="APPROVAL_EXPIRED", now=now)
            await self._session.commit()
            raise APIError(409, "approval_expired", "This approval has expired.")
        if not await self._binding_is_current(run, approval):
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            approval.resolver_user_id = context.identity.user_id
            transition_run(
                run, AgentRunStatus.FAILED, reason_code="APPROVAL_BINDING_MISMATCH", now=now
            )
            await self._session.commit()
            raise APIError(
                409,
                "approval_mismatch",
                "The approved action could not be reconstructed safely.",
            )
        current_fingerprint = authorization_scope_fingerprint(context.scope)
        if approval.authorization_scope_fingerprint != current_fingerprint:
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            approval.resolver_user_id = context.identity.user_id
            transition_run(
                run, AgentRunStatus.FAILED, reason_code="AUTHORIZATION_SCOPE_CHANGED", now=now
            )
            await self._session.commit()
            raise APIError(
                409,
                "authorization_changed",
                "Authorization changed; the action was not executed.",
            )
        if run.initial_user_message_id is None:
            transition_run(
                run, AgentRunStatus.FAILED, reason_code="RESUME_MESSAGE_MISSING", now=now
            )
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            await self._session.commit()
            raise APIError(409, "resume_failed", "The run could not be resumed safely.")
        message = await self._session.get(Message, run.initial_user_message_id)
        if message is None or message.role != "user" or message.user_id != context.identity.user_id:
            transition_run(
                run, AgentRunStatus.FAILED, reason_code="RESUME_MESSAGE_INVALID", now=now
            )
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            await self._session.commit()
            raise APIError(409, "resume_failed", "The run could not be resumed safely.")

        try:
            reconstructed_steps = await self._reconstruct_completed_steps(context, run_id=run.id)
        except Exception:
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            approval.resolver_user_id = context.identity.user_id
            transition_run(
                run, AgentRunStatus.FAILED, reason_code="RESUME_RECONSTRUCTION_FAILED", now=now
            )
            await self._session.commit()
            raise APIError(409, "resume_failed", "The run could not be resumed safely.") from None

        approval.status = ApprovalStatus.CONSUMED.value
        approval.resolved_at = now
        approval.consumed_at = now
        approval.resolver_user_id = context.identity.user_id
        transition_run(run, AgentRunStatus.RUNNING, reason_code="APPROVAL_CONSUMED", now=now)
        await self._session.commit()
        return await self._runner.run(
            context,
            conversation_id=run.conversation_id,
            question=message.content,
            response_mode=ResponseMode(run.response_mode),
            agent_control_mode=AgentControlMode(run.agent_control_mode),
            request_id=request_id,
            approved_action_hash=approval.action_argument_hash,
            resume_run=run,
            reconstructed_steps=reconstructed_steps,
        )

    async def reject(
        self, context: AuthorizationContext, *, run_id: UUID, approval_id: UUID
    ) -> SafelyTerminatedData:
        run, approval = await self._locked_owned(context, run_id=run_id, approval_id=approval_id)
        if (
            approval.status != ApprovalStatus.PENDING.value
            or run.status != AgentRunStatus.AWAITING_APPROVAL.value
        ):
            raise APIError(409, "approval_unavailable", "This approval is no longer available.")
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.REJECTED.value
        approval.resolved_at = now
        approval.resolver_user_id = context.identity.user_id
        transition_run(run, AgentRunStatus.CANCELLED, reason_code="APPROVAL_REJECTED", now=now)
        await self._session.commit()
        return SafelyTerminatedData(
            run_id=run.id, status="REJECTED", safe_message="The action was rejected and not run."
        )

    async def stop(self, context: AuthorizationContext, *, run_id: UUID) -> SafelyTerminatedData:
        tenant_id = resolve_home_tenant_id(context)
        run = await self._session.scalar(
            select(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.tenant_id == tenant_id,
                AgentRun.user_id == context.identity.user_id,
            )
            .with_for_update()
        )
        if run is None:
            raise APIError(404, "not_found", "Agent run was not found.")
        if run.status != AgentRunStatus.AWAITING_APPROVAL.value:
            raise APIError(409, "run_not_stoppable", "This run can no longer be stopped.")
        approval = await self._session.scalar(
            select(AgentApprovalRequest).where(
                AgentApprovalRequest.run_id == run.id,
                AgentApprovalRequest.status == ApprovalStatus.PENDING.value,
            )
        )
        now = datetime.now(UTC)
        if approval is not None:
            approval.status = ApprovalStatus.CANCELLED.value
            approval.resolved_at = now
            approval.resolver_user_id = context.identity.user_id
        transition_run(run, AgentRunStatus.CANCELLED, reason_code="RUN_STOPPED", now=now)
        await self._session.commit()
        return SafelyTerminatedData(
            run_id=run.id, status="CANCELLED", safe_message="The run was stopped safely."
        )

    async def current(self, context: AuthorizationContext, *, run_id: UUID) -> ApprovalStateData:
        tenant_id = resolve_home_tenant_id(context)
        row = (
            await self._session.execute(
                select(AgentRun, AgentApprovalRequest)
                .join(AgentApprovalRequest, AgentApprovalRequest.run_id == AgentRun.id)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.user_id == context.identity.user_id,
                )
                .order_by(AgentApprovalRequest.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise APIError(404, "not_found", "Agent run was not found.")
        run, approval = row
        grant = context.scope.grants[0]
        tool_name = approval.tool_name
        labels = {
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
        return ApprovalStateData(
            approval_id=approval.id,
            run_id=run.id,
            status=approval.status,
            action_label=labels[tool_name],
            safe_explanation="Use an allow-listed tool within your current authorized scope.",
            tool_name=tool_name,
            risk_level=approval.approval_risk_class,
            resource_type=(
                "authorized private memory"
                if tool_name in {"portfolio.search_memory", "portfolio.propose_memory"}
                else "authorized financial data"
                if ".calculate_" in tool_name or tool_name == "portfolio.query_financial_metrics"
                else "authorized portfolio documents"
            ),
            estimated_cost_class="low",
            safe_scope_summary=f"{grant.workspace_name} · {grant.primary_department.title()}",
            remaining_budget=RemainingApprovalBudgetData(
                steps=max(0, 4 - run.step_count), tools=max(0, 4 - run.step_count)
            ),
            expires_at=approval.expires_at,
        )

    async def change_request(
        self,
        context: AuthorizationContext,
        *,
        run_id: UUID,
        approval_id: UUID,
        content: str,
        request_id: str,
    ) -> AgentRunMessageData | AwaitingApprovalData:
        run, approval = await self._locked_owned(context, run_id=run_id, approval_id=approval_id)
        if (
            approval.status != ApprovalStatus.PENDING.value
            or run.status != AgentRunStatus.AWAITING_APPROVAL.value
        ):
            raise APIError(409, "approval_unavailable", "This approval is no longer available.")
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.SUPERSEDED.value
        approval.resolved_at = now
        approval.resolver_user_id = context.identity.user_id
        transition_run(run, AgentRunStatus.CANCELLED, reason_code="CHANGE_REQUESTED", now=now)
        conversation_id = run.conversation_id
        response_mode = ResponseMode(run.response_mode)
        control_mode = AgentControlMode(run.agent_control_mode)
        await self._session.commit()
        return await self._runner.run(
            context,
            conversation_id=conversation_id,
            question=content,
            response_mode=response_mode,
            agent_control_mode=control_mode,
            request_id=request_id,
        )
