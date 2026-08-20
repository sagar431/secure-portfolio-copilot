from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.embeddings.contracts import EmbeddingProvider, EmbeddingProviderError
from app.ingestion.audit import record_document_event
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.retrieval.evaluation import evaluate_curated_query
from app.retrieval.repository import get_authorized_index_status, search_authorized_chunks
from app.schemas.retrieval import (
    AuthorizedSearchData,
    AuthorizedSearchResultData,
    RetrievalEvaluationComplete,
    RetrievalEvaluationNotRun,
    SearchCitationData,
    SearchDocumentData,
    SearchEmbeddingData,
    SearchIndexingData,
    SearchScopeData,
    SearchScopeGrantData,
    SearchScoresData,
    SearchSourceData,
    SearchWorkspaceData,
)


def _query_grants(context: AuthorizationContext) -> SearchScopeData:
    grants = tuple(
        SearchScopeGrantData(
            workspace=SearchWorkspaceData(
                id=grant.workspace_id,
                slug=grant.workspace_slug,
                name=grant.workspace_name,
            ),
            company_ids=grant.company_ids,
            company_slugs=grant.company_slugs,
            query_departments=tuple(item.key for item in grant.departments),
        )
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
    )
    return SearchScopeData(grants=grants)


def _source_type(value: str) -> Literal["PDF", "XLSX", "CSV", "UNKNOWN"]:
    source_types: dict[str, Literal["PDF", "XLSX", "CSV", "UNKNOWN"]] = {
        "pdf": "PDF",
        "xlsx": "XLSX",
        "csv": "CSV",
    }
    return source_types.get(value, "UNKNOWN")


class AuthorizedSearchService:
    def __init__(self, session: AsyncSession, embedding_provider: EmbeddingProvider) -> None:
        self.session = session
        self.embedding_provider = embedding_provider

    async def search(
        self,
        context: AuthorizationContext,
        *,
        query: str,
        top_k: int,
        request_id: str,
    ) -> AuthorizedSearchData:
        if not any(
            Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants
        ):
            await record_document_event(
                self.session,
                event_type="authorized_document_search",
                outcome="deny",
                reason_code="DENY_CAPABILITY",
                request_id=request_id,
                actor_user_id=context.identity.user_id,
            )
            await self.session.commit()
            raise APIError(403, "forbidden", "Document search is not permitted.")
        try:
            await self.embedding_provider.ensure_ready()
            vectors = await self.embedding_provider.embed((query,))
            if len(vectors) != 1:
                raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE")
            model = self.embedding_provider.model
            candidates = await search_authorized_chunks(
                self.session,
                context.scope,
                query=query,
                query_embedding=vectors[0],
                model_name=model.name,
                model_version=model.version,
                dimensions=model.dimensions,
                top_k=top_k,
            )
        except (EmbeddingProviderError, ValueError):
            raise APIError(
                503, "embedding_unavailable", "Document search is temporarily unavailable."
            ) from None
        status = await get_authorized_index_status(self.session, context.scope)
        await record_document_event(
            self.session,
            event_type="authorized_document_search",
            outcome="allow",
            reason_code="AUTHORIZED_SEARCH_COMPLETED",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            metadata={
                "result_count": len(candidates),
                "top_k": top_k,
                "active_chunk_count": status.active_chunk_count,
                "indexed_document_count": status.indexed_document_count,
                "chunk_ids": ",".join(str(item.chunk_id) for item in candidates),
                "document_ids": ",".join(sorted({str(item.document_id) for item in candidates})),
            },
        )
        await self.session.commit()
        results = tuple(
            AuthorizedSearchResultData(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                version_number=item.version_number,
                excerpt=item.excerpt,
                scores=SearchScoresData(
                    keyword=item.keyword_score,
                    vector=item.vector_score,
                    final=item.final_score,
                ),
                citation=SearchCitationData(
                    document_id=item.document_id,
                    document_version_id=item.document_version_id,
                    chunk_id=item.chunk_id,
                    document_title=item.filename,
                    version_number=item.version_number,
                    excerpt=item.excerpt,
                    page_number=item.page_number,
                    sheet_name=item.sheet_name,
                    row_start=item.row_start,
                    row_end=item.row_end,
                    cell_start=item.cell_start,
                    cell_end=item.cell_end,
                ),
                source=SearchSourceData(
                    page_number=item.page_number,
                    sheet_name=item.sheet_name,
                    row_start=item.row_start,
                    row_end=item.row_end,
                    cell_start=item.cell_start,
                    cell_end=item.cell_end,
                ),
                document=SearchDocumentData(
                    filename=item.filename,
                    source_type=_source_type(item.source_type),
                    document_type=item.document_type,
                    reporting_period=item.reporting_period,
                    tenant_slug=item.tenant_slug,
                    company_slug=item.company_slug,
                    department=item.department,
                    visibility=item.visibility,
                    classification=item.classification,
                ),
            )
            for item in candidates
        )
        indexing_status: Literal["ready", "indexing", "degraded"] = "ready"
        embedding_status: Literal["ready", "indexing", "degraded", "unavailable"] = "ready"
        if status.pending_chunk_count:
            indexing_status = "indexing"
            embedding_status = "indexing"
        elif status.failed_chunk_count:
            indexing_status = "degraded"
            embedding_status = "degraded"
        evaluation = evaluate_curated_query(query, tuple(candidates), context.scope)
        evaluation_summary = (
            RetrievalEvaluationComplete(
                dataset_name=evaluation.dataset_name,
                curated_query_count=evaluation.curated_query_count,
                recall_at_5=evaluation.recall_at_5,
                expected_top_5_hits=evaluation.expected_top_5_hits,
                authorization_leak_count=evaluation.authorization_leak_count,
            )
            if evaluation is not None
            else RetrievalEvaluationNotRun()
        )
        return AuthorizedSearchData(
            status=indexing_status,
            query=query,
            top_k=top_k,
            result_count=len(results),
            authorized_scope=_query_grants(context),
            indexing=SearchIndexingData(
                status=indexing_status,
                active_chunk_count=status.active_chunk_count,
                indexed_document_count=status.indexed_document_count,
                embedding=SearchEmbeddingData(
                    status=embedding_status,
                    model=f"{model.name}:{model.version}",
                    dimensions=model.dimensions,
                    embedded_chunk_count=status.embedded_chunk_count,
                    pending_chunk_count=status.pending_chunk_count,
                    failed_chunk_count=status.failed_chunk_count,
                ),
            ),
            evaluation_summary=evaluation_summary,
            results=results,
        )
