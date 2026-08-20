from __future__ import annotations

import json

import pytest
from mcp import Client

from app.mcp_gateway.contracts import ApprovedToolName, StructuredToolObservation
from app.mcp_gateway.server import build_in_process_mcp_server
from tests.unit.mcp_gateway.test_gateway import _authorization_scope, _gateway


@pytest.mark.asyncio
async def test_official_mcp_sdk_in_process_structured_output_smoke() -> None:
    gateway, search, _ = _gateway()
    server = build_in_process_mcp_server(
        gateway,
        authorization_scope=_authorization_scope(),
        permitted_tools=frozenset({ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS}),
        request_id="mcp-smoke",
    )

    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        search_tool = next(
            tool
            for tool in listed.tools
            if tool.name == ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS
        )
        result = await client.call_tool(
            ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
            {"query": "revenue", "top_k": 5},
        )

    listed_names = {tool.name for tool in listed.tools}
    assert listed_names == {ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS}
    assert "authorization_scope" not in search_tool.input_schema.get("properties", {})
    assert "tenant_id" not in search_tool.input_schema.get("properties", {})
    assert result.is_error is False
    assert result.structured_content is not None
    validated = StructuredToolObservation.model_validate_json(
        json.dumps(result.structured_content), strict=True
    )
    assert validated.reason_code == "TOOL_COMPLETED"
    assert search.call_count == 1
