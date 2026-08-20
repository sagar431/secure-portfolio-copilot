from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.mcp_gateway.contracts import (
    ApprovedToolName,
    EvidenceLocation,
    GatewayReasonCode,
    GetDocumentExcerptInput,
    SearchAuthorizedDocumentsInput,
    StructuredToolObservation,
    ToolEvidence,
    ToolPayload,
    sanitize_observation,
)
from app.mcp_gateway.errors import (
    GatewayConfigurationError,
    ToolAuthorizationError,
    ToolTransientError,
)
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)


def _authorization_scope(*, with_query_capability: bool = True) -> AuthorizationScope:
    identity = TrustedIdentity(
        user_id=uuid4(),
        email="owner@example.com",
        display_name="Owner",
    )
    capabilities = (Capability.QUERY_DOCUMENTS,) if with_query_capability else ()
    return AuthorizationScope(
        identity=identity,
        grants=(
            AuthorizationGrant(
                membership_id=uuid4(),
                home_tenant_id=uuid4(),
                home_tenant_slug="home",
                home_tenant_name="Home",
                workspace_id=uuid4(),
                workspace_slug="workspace",
                workspace_name="Workspace",
                role="analyst",
                primary_department="finance",
                company_ids=(uuid4(),),
                company_slugs=("portfolio",),
                departments=(
                    DepartmentAccess(key="finance", source=GrantSource.PRIMARY_DEPARTMENT),
                ),
                capabilities=capabilities,
            ),
        ),
    )


def _payload(*, excerpt: str = "Authorized evidence") -> ToolPayload:
    return ToolPayload(
        evidence=(
            ToolEvidence(
                document_id=uuid4(),
                document_version_id=uuid4(),
                chunk_id=uuid4(),
                document_title="report.pdf",
                version_number=1,
                excerpt=excerpt,
                location=EvidenceLocation(page_number=1),
            ),
        )
    )


class FakeAdapter:
    required_capability = Capability.QUERY_DOCUMENTS
    output_model: type[BaseModel] = ToolPayload

    def __init__(
        self,
        name: ApprovedToolName,
        input_model: type[BaseModel],
        responses: Sequence[object] = (),
    ) -> None:
        self.name = name
        self.input_model = input_model
        self._responses = list(responses) or [_payload()]
        self.call_count = 0
        self.seen_scope: AuthorizationScope | None = None

    async def invoke(
        self,
        *,
        arguments: BaseModel,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object:
        del arguments, request_id
        self.call_count += 1
        self.seen_scope = authorization_scope
        item = self._responses[min(self.call_count - 1, len(self._responses) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


class SlowAdapter(FakeAdapter):
    async def invoke(
        self,
        *,
        arguments: BaseModel,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object:
        del arguments, request_id
        self.call_count += 1
        self.seen_scope = authorization_scope
        await asyncio.sleep(0.03)
        return _payload()


def _gateway(
    *,
    search: FakeAdapter | None = None,
    excerpt: FakeAdapter | None = None,
    timeout_seconds: float = 0.1,
) -> tuple[ApprovedToolGateway, FakeAdapter, FakeAdapter]:
    search_adapter = search or FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
    )
    excerpt_adapter = excerpt or FakeAdapter(
        ApprovedToolName.GET_DOCUMENT_EXCERPT,
        GetDocumentExcerptInput,
    )
    gateway = ApprovedToolGateway(
        [search_adapter, excerpt_adapter],
        timeout_seconds=timeout_seconds,
    )
    return gateway, search_adapter, excerpt_adapter


async def _search(
    gateway: ApprovedToolGateway,
    scope: AuthorizationScope,
    *,
    arguments: dict[str, object] | None = None,
    permitted_tools: frozenset[str] | None = None,
) -> StructuredToolObservation:
    return await gateway.execute(
        tool_name=ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        arguments=arguments or {"query": "revenue", "top_k": 5},
        authorization_scope=scope,
        permitted_tools=permitted_tools
        or frozenset({ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS}),
        request_id="request-1",
    )


@pytest.mark.asyncio
async def test_host_scope_is_injected_out_of_band_and_cannot_be_overridden() -> None:
    gateway, search, _ = _gateway()
    trusted_scope = _authorization_scope()

    rejected = await _search(
        gateway,
        trusted_scope,
        arguments={
            "query": "revenue",
            "top_k": 5,
            "authorization_scope": {"user_id": str(uuid4())},
        },
    )
    allowed = await _search(gateway, trusted_scope)

    assert rejected.reason_code == GatewayReasonCode.INPUT_SCHEMA_REJECTED
    assert search.call_count == 1
    assert search.seen_scope is trusted_scope
    assert allowed.status == "completed"


@pytest.mark.asyncio
async def test_unknown_and_non_shortlisted_tools_never_execute() -> None:
    gateway, search, _ = _gateway()
    scope = _authorization_scope()

    unknown = await gateway.execute(
        tool_name="host.run_user_code",
        arguments={},
        authorization_scope=scope,
        permitted_tools=frozenset({"host.run_user_code"}),
        request_id="request-1",
    )
    not_shortlisted = await _search(gateway, scope, permitted_tools=frozenset({"other.tool"}))

    assert unknown.reason_code == GatewayReasonCode.UNKNOWN_TOOL
    assert unknown.tool_name is None
    assert not_shortlisted.reason_code == GatewayReasonCode.TOOL_NOT_SHORTLISTED
    assert search.call_count == 0


@pytest.mark.asyncio
async def test_missing_capability_denies_before_adapter_execution() -> None:
    gateway, search, _ = _gateway()

    result = await _search(gateway, _authorization_scope(with_query_capability=False))

    assert result.reason_code == GatewayReasonCode.AUTHORIZATION_DENIED
    assert search.call_count == 0


@pytest.mark.asyncio
async def test_strict_schema_rejects_coercion_and_ownership_fields() -> None:
    gateway, search, _ = _gateway()
    scope = _authorization_scope()

    coerced = await _search(gateway, scope, arguments={"query": "revenue", "top_k": "5"})
    tenant_override = await _search(
        gateway,
        scope,
        arguments={"query": "revenue", "top_k": 5, "tenant_id": str(uuid4())},
    )

    assert coerced.reason_code == GatewayReasonCode.INPUT_SCHEMA_REJECTED
    assert tenant_override.reason_code == GatewayReasonCode.INPUT_SCHEMA_REJECTED
    assert search.call_count == 0


@pytest.mark.asyncio
async def test_corrupt_output_fails_closed_without_content_leakage() -> None:
    corrupt = {"evidence": (), "raw_error": "SECRET-CONTENT"}
    search = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
        [corrupt],
    )
    gateway, _, _ = _gateway(search=search)

    result = await _search(gateway, _authorization_scope())

    assert result.reason_code == GatewayReasonCode.OUTPUT_SCHEMA_REJECTED
    assert result.evidence == ()
    assert "SECRET-CONTENT" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_transient_failure_retries_once_then_succeeds() -> None:
    search = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
        [ToolTransientError(), _payload()],
    )
    gateway, _, _ = _gateway(search=search)

    result = await _search(gateway, _authorization_scope())

    assert result.status == "completed"
    assert result.retry_count == 1
    assert search.call_count == 2


@pytest.mark.asyncio
async def test_timeout_retries_at_most_once() -> None:
    search = SlowAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
    )
    gateway, _, _ = _gateway(search=search, timeout_seconds=0.001)

    result = await _search(gateway, _authorization_scope())

    assert result.reason_code == GatewayReasonCode.TOOL_TIMEOUT
    assert result.retry_count == 1
    assert search.call_count == 2


@pytest.mark.asyncio
async def test_authorization_denial_is_never_retried() -> None:
    search = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
        [ToolAuthorizationError()],
    )
    gateway, _, _ = _gateway(search=search)

    result = await _search(gateway, _authorization_scope())

    assert result.reason_code == GatewayReasonCode.AUTHORIZATION_DENIED
    assert result.retry_count == 0
    assert search.call_count == 1


def test_startup_rejects_duplicate_namespace_schema_and_capability_mismatches() -> None:
    search = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
    )
    excerpt = FakeAdapter(
        ApprovedToolName.GET_DOCUMENT_EXCERPT,
        GetDocumentExcerptInput,
    )
    with pytest.raises(GatewayConfigurationError, match="DUPLICATE_TOOL_NAME"):
        ApprovedToolGateway([search, search, excerpt])

    unnamespaced = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
    )
    unnamespaced.name = cast(ApprovedToolName, "run_user_code")
    with pytest.raises(GatewayConfigurationError, match="UNAPPROVED_TOOL_NAMESPACE"):
        ApprovedToolGateway([unnamespaced, excerpt])

    wrong_schema = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        GetDocumentExcerptInput,
    )
    with pytest.raises(GatewayConfigurationError, match="INPUT_SCHEMA_MISMATCH"):
        ApprovedToolGateway([wrong_schema, excerpt])

    wrong_capability = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
    )
    wrong_capability.required_capability = Capability.MANAGE_UPLOADS
    with pytest.raises(GatewayConfigurationError, match="CAPABILITY_MISMATCH"):
        ApprovedToolGateway([wrong_capability, excerpt])


def test_authorized_catalog_is_capability_and_request_shortlist_filtered() -> None:
    alice = _authorization_scope()
    leo = _authorization_scope()

    alice_catalog = ApprovedToolGateway.authorized_catalog(
        alice,
        frozenset({ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS}),
    )
    leo_catalog = ApprovedToolGateway.authorized_catalog(
        leo,
        frozenset({ApprovedToolName.GET_DOCUMENT_EXCERPT}),
    )
    denied_catalog = ApprovedToolGateway.authorized_catalog(
        _authorization_scope(with_query_capability=False),
        frozenset(item.value for item in ApprovedToolName),
    )

    assert alice_catalog == (ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,)
    assert leo_catalog == (ApprovedToolName.GET_DOCUMENT_EXCERPT,)
    assert denied_catalog == ()


@pytest.mark.parametrize(
    "location",
    [
        {"page_number": 1, "sheet_name": "Sheet1"},
        {"page_number": None, "sheet_name": None},
        {"sheet_name": "Sheet1", "row_start": 4, "row_end": 2},
        {"sheet_name": "Sheet1", "cell_start": "D4", "cell_end": "B2"},
        {"page_number": 1, "row_start": 1, "row_end": 2},
    ],
)
def test_evidence_location_rejects_corrupt_provenance(location: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EvidenceLocation.model_validate(location, strict=True)


@pytest.mark.asyncio
async def test_sanitized_trace_contains_only_ids_and_status_metadata() -> None:
    search = FakeAdapter(
        ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS,
        SearchAuthorizedDocumentsInput,
        [_payload(excerpt="HIGHLY-SENSITIVE-EVIDENCE")],
    )
    gateway, _, _ = _gateway(search=search)

    observation = await _search(gateway, _authorization_scope())
    trace = sanitize_observation(observation)
    serialized = trace.model_dump_json()

    assert trace.evidence_refs
    assert "HIGHLY-SENSITIVE-EVIDENCE" not in serialized
    assert "revenue" not in serialized
    assert "query" not in serialized
