from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculations.contracts import CalculationMetric
from app.calculations.engine import CalculationError
from app.calculations.repository import (
    CalculationAuthorizationError,
    calculate_authorized_metric,
)
from app.core.errors import APIError
from app.embeddings.contracts import EmbeddingProvider
from app.mcp_gateway.contracts import (
    ApprovedToolName,
    CalculateFinancialMetricInput,
    CalculationPayload,
    EvidenceLocation,
    GatewayReasonCode,
    GetDocumentExcerptInput,
    SearchAuthorizedDocumentsInput,
    ToolEvidence,
    ToolPayload,
)
from app.mcp_gateway.errors import (
    GatewayConfigurationError,
    ToolAdapterError,
    ToolAuthorizationError,
    ToolTransientError,
)
from app.mcp_gateway.gateway import TOOL_MANIFEST
from app.models.documents import DocumentChunk, DocumentVersion
from app.models.identity import Capability
from app.policies.models import AuthorizationContext, AuthorizationScope
from app.retrieval.limits import MAX_EXCERPT_CHARACTERS
from app.retrieval.repository import _authorized_base
from app.retrieval.service import AuthorizedSearchService


def validate_production_tool_catalog() -> None:
    """Fail application startup if the static production catalog drifts."""
    adapter_types = (
        SearchAuthorizedDocumentsAdapter,
        GetDocumentExcerptAdapter,
        CalculateEbitdaMarginAdapter,
        CalculateRevenueGrowthAdapter,
        CalculateNetProfitMarginAdapter,
    )
    seen: set[ApprovedToolName] = set()
    for adapter_type in adapter_types:
        name = adapter_type.name
        if name in seen:
            raise GatewayConfigurationError("DUPLICATE_TOOL_NAME")
        seen.add(name)
        expected = TOOL_MANIFEST.get(name)
        if expected is None:
            raise GatewayConfigurationError("UNAPPROVED_TOOL_NAMESPACE")
        if adapter_type.input_model.model_json_schema() != expected.input_model.model_json_schema():
            raise GatewayConfigurationError("INPUT_SCHEMA_MISMATCH")
        if (
            adapter_type.output_model.model_json_schema()
            != expected.output_model.model_json_schema()
        ):
            raise GatewayConfigurationError("OUTPUT_SCHEMA_MISMATCH")
        if adapter_type.required_capability != expected.required_capability:
            raise GatewayConfigurationError("CAPABILITY_MISMATCH")
    if seen != set(TOOL_MANIFEST):
        raise GatewayConfigurationError("TOOL_CATALOG_INCOMPLETE")


def _require_query_capability(scope: AuthorizationScope) -> None:
    if not any(Capability.QUERY_DOCUMENTS in grant.capabilities for grant in scope.grants):
        raise ToolAuthorizationError


class SearchAuthorizedDocumentsAdapter:
    name = ApprovedToolName.SEARCH_AUTHORIZED_DOCUMENTS
    input_model = SearchAuthorizedDocumentsInput
    output_model = ToolPayload
    required_capability = Capability.QUERY_DOCUMENTS

    def __init__(self, session: AsyncSession, embedding_provider: EmbeddingProvider) -> None:
        self._service = AuthorizedSearchService(session, embedding_provider)

    async def invoke(
        self,
        *,
        arguments: object,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object:
        if not isinstance(arguments, SearchAuthorizedDocumentsInput):
            raise TypeError("Gateway input contract mismatch")
        _require_query_capability(authorization_scope)
        context = AuthorizationContext(
            identity=authorization_scope.identity,
            scope=authorization_scope,
        )
        try:
            result = await self._service.search(
                context,
                query=arguments.query,
                top_k=arguments.top_k,
                request_id=request_id,
            )
        except APIError as exc:
            if exc.status_code in {401, 403, 404}:
                raise ToolAuthorizationError from None
            raise ToolTransientError from None
        return ToolPayload(
            evidence=tuple(
                ToolEvidence(
                    document_id=item.citation.document_id,
                    document_version_id=item.citation.document_version_id,
                    chunk_id=item.citation.chunk_id,
                    document_title=item.citation.document_title,
                    version_number=item.citation.version_number,
                    excerpt=item.citation.excerpt,
                    location=EvidenceLocation(
                        page_number=item.citation.page_number,
                        sheet_name=item.citation.sheet_name,
                        row_start=item.citation.row_start,
                        row_end=item.citation.row_end,
                        cell_start=item.citation.cell_start,
                        cell_end=item.citation.cell_end,
                    ),
                )
                for item in result.results
            )
        )


class GetDocumentExcerptAdapter:
    name = ApprovedToolName.GET_DOCUMENT_EXCERPT
    input_model = GetDocumentExcerptInput
    output_model = ToolPayload
    required_capability = Capability.QUERY_DOCUMENTS

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def invoke(
        self,
        *,
        arguments: object,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object:
        del request_id
        if not isinstance(arguments, GetDocumentExcerptInput):
            raise TypeError("Gateway input contract mismatch")
        _require_query_capability(authorization_scope)
        statement = (
            _authorized_base(authorization_scope)
            .where(
                DocumentChunk.document_id == arguments.document_id,
                DocumentChunk.id == arguments.chunk_id,
            )
            .with_only_columns(
                DocumentChunk.document_id,
                DocumentChunk.document_version_id,
                DocumentChunk.id,
                DocumentVersion.safe_filename,
                DocumentChunk.version_number,
                func.left(DocumentChunk.content, MAX_EXCERPT_CHARACTERS),
                DocumentChunk.page_number,
                DocumentChunk.sheet_name,
                DocumentChunk.row_start,
                DocumentChunk.row_end,
                DocumentChunk.cell_start,
                DocumentChunk.cell_end,
            )
            .limit(1)
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            # Missing and unauthorized are intentionally indistinguishable.
            raise ToolAuthorizationError
        return ToolPayload(
            evidence=(
                ToolEvidence(
                    document_id=row[0],
                    document_version_id=row[1],
                    chunk_id=row[2],
                    document_title=row[3],
                    version_number=row[4],
                    excerpt=row[5],
                    location=EvidenceLocation(
                        page_number=row[6],
                        sheet_name=row[7],
                        row_start=row[8],
                        row_end=row[9],
                        cell_start=row[10],
                        cell_end=row[11],
                    ),
                ),
            )
        )


class _CalculateFinancialMetricAdapter:
    input_model = CalculateFinancialMetricInput
    output_model = CalculationPayload
    required_capability = Capability.QUERY_DOCUMENTS
    metric: CalculationMetric

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def invoke(
        self,
        *,
        arguments: object,
        authorization_scope: AuthorizationScope,
        request_id: str,
    ) -> object:
        del request_id
        if not isinstance(arguments, CalculateFinancialMetricInput):
            raise TypeError("Gateway input contract mismatch")
        _require_query_capability(authorization_scope)
        try:
            result = await calculate_authorized_metric(
                self._session,
                authorization_scope,
                metric=self.metric,
                company_slug=arguments.company_slug,
                period=arguments.reporting_period,
            )
        except CalculationAuthorizationError:
            raise ToolAuthorizationError from None
        except CalculationError as exc:
            raise ToolAdapterError(GatewayReasonCode(exc.code.value)) from None
        return CalculationPayload(calculations=(result,))


class CalculateEbitdaMarginAdapter(_CalculateFinancialMetricAdapter):
    name = ApprovedToolName.CALCULATE_EBITDA_MARGIN
    metric = CalculationMetric.EBITDA_MARGIN


class CalculateRevenueGrowthAdapter(_CalculateFinancialMetricAdapter):
    name = ApprovedToolName.CALCULATE_REVENUE_GROWTH
    metric = CalculationMetric.REVENUE_GROWTH


class CalculateNetProfitMarginAdapter(_CalculateFinancialMetricAdapter):
    name = ApprovedToolName.CALCULATE_NET_PROFIT_MARGIN
    metric = CalculationMetric.NET_PROFIT_MARGIN
