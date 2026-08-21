import json

from mcp import Client

from app.agent.models import Action, ObservationStatus, StructuredObservation
from app.chat.contracts import GroundedEvidence
from app.mcp_gateway.contracts import (
    ApprovedToolName,
    GatewayReasonCode,
    StructuredToolObservation,
    ToolEvidence,
)
from app.mcp_gateway.gateway import TOOL_MANIFEST
from app.mcp_gateway.gateway import ApprovedToolGateway as MCPApprovedToolGateway
from app.mcp_gateway.server import build_in_process_mcp_server
from app.policies.models import AuthorizationContext


class AgentGatewayAdapter:
    """Converts one typed agent action to the concrete trusted MCP gateway contract."""

    def __init__(self, gateway: MCPApprovedToolGateway) -> None:
        self._gateway = gateway
        self._evidence_sequence = 0

    def _evidence(self, item: ToolEvidence) -> GroundedEvidence:
        self._evidence_sequence += 1
        return GroundedEvidence(
            evidence_id=f"ev_{self._evidence_sequence}",
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

    async def execute(
        self,
        *,
        action: Action,
        authorization_context: AuthorizationContext,
        permitted_tools: frozenset[str],
        request_id: str,
    ) -> StructuredObservation:
        if authorization_context.identity != authorization_context.scope.identity:
            return StructuredObservation(
                tool_name=action.action_name or "portfolio.invalid",
                status=ObservationStatus.DENIED,
                duration_ms=0,
                reason_code="AUTHORIZATION_IDENTITY_MISMATCH",
            )
        try:
            approved_name = ApprovedToolName(action.action_name or "")
            raw_arguments = action.arguments.model_dump(mode="json")
            TOOL_MANIFEST[approved_name].input_model.model_validate_json(
                json.dumps(raw_arguments), strict=True
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return StructuredObservation(
                tool_name=action.action_name or "portfolio.invalid",
                status=ObservationStatus.DENIED,
                duration_ms=0,
                reason_code=GatewayReasonCode.INPUT_SCHEMA_REJECTED.value,
            )
        server = build_in_process_mcp_server(
            self._gateway,
            authorization_scope=authorization_context.scope,
            permitted_tools=permitted_tools,
            request_id=request_id,
        )
        try:
            async with Client(server, raise_exceptions=True) as client:
                response = await client.call_tool(action.action_name or "", raw_arguments)
            if response.is_error or response.structured_content is None:
                raise ValueError("MCP tool failed safely")
            result = StructuredToolObservation.model_validate_json(
                json.dumps(response.structured_content), strict=True
            )
        except Exception:
            return StructuredObservation(
                tool_name=action.action_name or "portfolio.invalid",
                status=ObservationStatus.ERROR,
                duration_ms=0,
                reason_code=GatewayReasonCode.TOOL_FAILED_SAFE.value,
            )
        if result.status == "completed":
            status = ObservationStatus.SUCCESS
        elif result.status == "denied":
            status = ObservationStatus.DENIED
        elif result.reason_code == GatewayReasonCode.TOOL_TIMEOUT:
            status = ObservationStatus.TIMEOUT
        else:
            status = ObservationStatus.ERROR
        return StructuredObservation(
            tool_name=result.tool_name.value
            if result.tool_name is not None
            else action.action_name or "portfolio.invalid",
            status=status,
            evidence=tuple(self._evidence(item) for item in result.evidence),
            duration_ms=result.duration_ms,
            retryable=False,
            retry_count=result.retry_count,
            reason_code=result.reason_code.value,
        )
