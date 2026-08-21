from __future__ import annotations

from uuid import UUID

from mcp.server.mcpserver import MCPServer

from app.mcp_gateway.contracts import ApprovedToolName, StructuredToolObservation
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.policies.models import AuthorizationScope


def build_in_process_mcp_server(
    gateway: ApprovedToolGateway,
    *,
    authorization_scope: AuthorizationScope,
    permitted_tools: frozenset[str],
    request_id: str,
) -> MCPServer:
    """Build a per-request server whose trusted scope exists only in host closures."""
    server = MCPServer(
        "secure-portfolio-approved-tools",
        version="1.0.0",
        instructions="Use only the statically registered portfolio evidence and calculation tools.",
        warn_on_duplicate_tools=True,
    )

    catalog = gateway.authorized_catalog(authorization_scope, permitted_tools)
    if ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS in catalog:

        @server.tool(name="portfolio.search_authorized_documents", structured_output=True)
        async def search_authorized_documents(query: str, top_k: int) -> StructuredToolObservation:
            return await gateway.execute(
                tool_name="portfolio.search_authorized_documents",
                arguments={"query": query, "top_k": top_k},
                authorization_scope=authorization_scope,
                permitted_tools=permitted_tools,
                request_id=request_id,
            )

    if ApprovedToolName.GET_DOCUMENT_EXCERPT in catalog:

        @server.tool(name="portfolio.get_document_excerpt", structured_output=True)
        async def get_document_excerpt(
            document_id: UUID, chunk_id: UUID
        ) -> StructuredToolObservation:
            return await gateway.execute(
                tool_name="portfolio.get_document_excerpt",
                arguments={"document_id": document_id, "chunk_id": chunk_id},
                authorization_scope=authorization_scope,
                permitted_tools=permitted_tools,
                request_id=request_id,
            )

    calculator_tools = (
        ApprovedToolName.CALCULATE_EBITDA_MARGIN,
        ApprovedToolName.CALCULATE_REVENUE_GROWTH,
        ApprovedToolName.CALCULATE_NET_PROFIT_MARGIN,
    )

    def register_calculator(calculator_name: ApprovedToolName) -> None:
        async def calculate_metric(
            company_slug: str,
            reporting_period: str,
        ) -> StructuredToolObservation:
            return await gateway.execute(
                tool_name=calculator_name.value,
                arguments={
                    "company_slug": company_slug,
                    "reporting_period": reporting_period,
                },
                authorization_scope=authorization_scope,
                permitted_tools=permitted_tools,
                request_id=request_id,
            )

        server.tool(name=calculator_name.value, structured_output=True)(calculate_metric)

    for calculator_name in calculator_tools:
        if calculator_name in catalog:
            register_calculator(calculator_name)

    return server
