import json
import logging
from pathlib import Path
from uuid import UUID

import pytest
from anyio import Path as AsyncPath
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update

from app.api.routes import documents as document_routes
from app.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingProviderError
from app.models.documents import Document, DocumentAuditEvent, DocumentChunk, DocumentVersion
from app.scripts.seed_development import seed_id
from tests.conftest import DEMO_PASSWORD, AuthHarness

DATA_ROOT = Path(__file__).resolve().parents[3] / "Simulated_data"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return str(response.json()["data"]["access_token"])


def _metadata(
    *,
    workspace: str,
    department: str,
    document_type: str,
    reporting_period: str | None,
) -> dict[str, str | None]:
    visibility, classification = {
        "finance": ("DEPARTMENT_PRIVATE", "FINANCE_ONLY"),
        "legal": ("DEPARTMENT_PRIVATE", "LEGAL_ONLY_CONFIDENTIAL"),
        "shared": ("TENANT_SHARED", "TENANT_SHARED"),
    }[department]
    return {
        "tenant_id": str(seed_id("tenant", workspace)),
        "company_id": str(seed_id("company", f"{workspace}-main")),
        "department": department,
        "visibility": visibility,
        "classification": classification,
        "document_type": document_type,
        "reporting_period": reporting_period,
    }


async def _upload(
    client: AsyncClient,
    token: str,
    *,
    relative_path: str,
    media_type: str,
    metadata: dict[str, str | None],
    idempotency_key: str,
    endpoint: str = "/api/admin/documents",
) -> Response:
    path = DATA_ROOT / relative_path
    contents = await AsyncPath(path).read_bytes()
    return await client.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
        },
        data={"metadata": json.dumps(metadata)},
        files={"file": (path.name, contents, media_type)},
    )


async def _approve(client: AsyncClient, token: str, document: dict[str, object]) -> Response:
    version = document["version"]
    assert isinstance(version, dict)
    return await client.post(
        f"/api/admin/documents/{document['id']}/versions/{version['id']}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _upload_and_approve(
    client: AsyncClient,
    token: str,
    *,
    relative_path: str,
    media_type: str,
    metadata: dict[str, str | None],
    idempotency_key: str,
) -> dict[str, object]:
    response = await _upload(
        client,
        token,
        relative_path=relative_path,
        media_type=media_type,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )
    assert response.status_code == 201, response.text
    document = response.json()["data"]["document"]
    approved = await _approve(client, token, document)
    assert approved.status_code == 200, approved.text
    return document


async def _search(client: AsyncClient, token: str, query: str, top_k: int = 20) -> Response:
    return await client.post(
        "/api/development/authorized-search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": query, "top_k": top_k},
    )


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_approval_indexes_inherited_pdf_metadata_and_delete_removes_search(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    response = await _upload(
        auth_harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="FINANCIAL_REPORT",
            reporting_period="FY2025",
        ),
        idempotency_key="search-pdf-approval-0001",
    )
    assert response.status_code == 201, response.text
    document_data = response.json()["data"]["document"]
    document_id = UUID(document_data["id"])
    version_id = UUID(document_data["version"]["id"])

    async with auth_harness.session_factory() as session:
        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version_id)
                )
            ).scalar_one()
        )
        assert count == 0

    approved = await _approve(auth_harness.client, nora, document_data)
    assert approved.status_code == 200, approved.text

    async with auth_harness.session_factory() as session:
        document = await session.get(Document, document_id)
        version = await session.get(DocumentVersion, version_id)
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version_id)
                    .order_by(DocumentChunk.ordinal)
                )
            )
            .scalars()
            .all()
        )
        assert document is not None and version is not None and chunks
        assert all(chunk.tenant_id == document.tenant_id for chunk in chunks)
        assert all(chunk.company_id == document.company_id for chunk in chunks)
        assert all(chunk.department_id == document.department_id for chunk in chunks)
        assert all(chunk.department == "finance" for chunk in chunks)
        assert all(chunk.visibility == document.visibility for chunk in chunks)
        assert all(chunk.classification == document.classification for chunk in chunks)
        assert all(chunk.document_id == document.id for chunk in chunks)
        assert all(chunk.document_version_id == version.id for chunk in chunks)
        assert all(chunk.version_number == version.version_number for chunk in chunks)
        assert all(chunk.version_status == "APPROVED" and chunk.active for chunk in chunks)
        assert all(chunk.embedding_status == "READY" for chunk in chunks)
        assert all(chunk.embedding is not None and len(chunk.embedding) == 768 for chunk in chunks)
        assert all(chunk.embedding_model_name == "nomic-embed-text" for chunk in chunks)
        assert all(chunk.embedding_model_version == "v1.5" for chunk in chunks)
        assert all(chunk.embedding_dimensions == 768 for chunk in chunks)
        assert all(chunk.embedding_chunk_hash == chunk.content_hash for chunk in chunks)
        assert all(chunk.page_number is not None and chunk.sheet_name is None for chunk in chunks)

    handler = _RecordingHandler()
    logging.getLogger("app.ingestion.audit").addHandler(handler)
    logging.getLogger("app.middleware.request_id").addHandler(handler)
    try:
        searched = await _search(
            auth_harness.client,
            alice,
            "Drivers of Margin Compression",
        )
    finally:
        logging.getLogger("app.ingestion.audit").removeHandler(handler)
        logging.getLogger("app.middleware.request_id").removeHandler(handler)
    assert searched.status_code == 200, searched.text
    payload = searched.json()["data"]
    assert payload["results"]
    assert payload["evaluation_summary"] == {
        "status": "complete",
        "dataset_name": "step5-synthetic-ground-truth-v1",
        "curated_query_count": 1,
        "recall_at_5": 1.0,
        "expected_top_5_hits": 1,
        "authorization_leak_count": 0,
    }
    assert {item["document_id"] for item in payload["results"]} == {str(document_id)}
    assert all(len(item["excerpt"]) <= 500 for item in payload["results"])
    assert all(item["source"]["page_number"] is not None for item in payload["results"])
    assert sum(len(item["excerpt"]) for item in payload["results"]) <= 20 * 500
    rendered_logs = json.dumps(
        [
            {
                key: value
                for key, value in record.__dict__.items()
                if isinstance(value, str | int | float | bool | type(None))
            }
            for record in handler.records
        ],
        default=str,
    )
    assert "Drivers of Margin Compression" not in rendered_logs
    assert payload["results"][0]["excerpt"] not in rendered_logs

    async with auth_harness.session_factory() as session:
        event = (
            (
                await session.execute(
                    select(DocumentAuditEvent)
                    .where(DocumentAuditEvent.event_type == "authorized_document_search")
                    .order_by(DocumentAuditEvent.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .one()
        )
        assert set(event.event_metadata) == {
            "result_count",
            "top_k",
            "active_chunk_count",
            "indexed_document_count",
            "chunk_ids",
            "document_ids",
        }
        assert set(str(event.event_metadata["chunk_ids"]).split(",")) == {
            item["chunk_id"] for item in payload["results"]
        }
        assert event.event_metadata["document_ids"] == str(document_id)
        assert "Drivers" not in json.dumps(event.event_metadata)

    deleted = await auth_harness.client.delete(
        f"/api/admin/documents/{document_id}",
        headers={"Authorization": f"Bearer {nora}"},
    )
    assert deleted.status_code == 200
    after_delete = await _search(auth_harness.client, alice, "Margin Compression")
    assert after_delete.status_code == 200
    assert after_delete.json()["data"]["results"] == []
    async with auth_harness.session_factory() as session:
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )
        assert chunks
        assert all(
            not chunk.active and chunk.document_deleted and chunk.version_deleted
            for chunk in chunks
        )
        assert all(
            chunk.embedding_status == "STALE" and chunk.embedding is None for chunk in chunks
        )


@pytest.mark.asyncio
async def test_xlsx_version_rejection_and_atomic_replacement_preserve_provenance(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    metadata = _metadata(
        workspace="orion",
        department="finance",
        document_type="SPREADSHEET",
        reporting_period="FY2024-FY2025",
    )
    relative_path = "orion/finance/Orion_FY2024_FY2025_Financials.xlsx"
    first = await _upload_and_approve(
        auth_harness.client,
        nora,
        relative_path=relative_path,
        media_type=XLSX_MEDIA_TYPE,
        metadata=metadata,
        idempotency_key="search-xlsx-version-0001",
    )
    document_id = UUID(str(first["id"]))
    first_version = UUID(str(first["version"]["id"]))  # type: ignore[index]

    rejected_upload = await _upload(
        auth_harness.client,
        nora,
        relative_path=relative_path,
        media_type=XLSX_MEDIA_TYPE,
        metadata=metadata,
        idempotency_key="search-xlsx-version-0002",
        endpoint=f"/api/admin/documents/{document_id}/versions",
    )
    assert rejected_upload.status_code == 201, rejected_upload.text
    rejected = rejected_upload.json()["data"]["document"]
    rejected_version = UUID(rejected["version"]["id"])
    reject = await auth_harness.client.post(
        f"/api/admin/documents/{document_id}/versions/{rejected_version}/reject",
        headers={"Authorization": f"Bearer {nora}"},
    )
    assert reject.status_code == 200
    invalid_approval = await _approve(auth_harness.client, nora, rejected)
    assert invalid_approval.status_code == 409

    replacement_upload = await _upload(
        auth_harness.client,
        nora,
        relative_path=relative_path,
        media_type=XLSX_MEDIA_TYPE,
        metadata=metadata,
        idempotency_key="search-xlsx-version-0003",
        endpoint=f"/api/admin/documents/{document_id}/versions",
    )
    assert replacement_upload.status_code == 201, replacement_upload.text
    replacement = replacement_upload.json()["data"]["document"]
    replacement_version = UUID(replacement["version"]["id"])

    async with auth_harness.session_factory() as session:
        old_active = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(
                        DocumentChunk.document_version_id == first_version,
                        DocumentChunk.active.is_(True),
                    )
                )
            ).scalar_one()
        )
        not_yet_indexed = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(
                        DocumentChunk.document_version_id.in_(
                            (rejected_version, replacement_version)
                        )
                    )
                )
            ).scalar_one()
        )
        assert old_active > 0
        assert not_yet_indexed == 0

    approved = await _approve(auth_harness.client, nora, replacement)
    assert approved.status_code == 200, approved.text

    async with auth_harness.session_factory() as session:
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.version_number, DocumentChunk.ordinal)
                )
            )
            .scalars()
            .all()
        )
        assert chunks
        assert not any(
            chunk.active for chunk in chunks if chunk.document_version_id == first_version
        )
        stale = [chunk for chunk in chunks if chunk.document_version_id == first_version]
        assert stale and all(
            chunk.embedding_status == "STALE"
            and chunk.embedding is None
            and chunk.embedding_model_name is None
            and chunk.embedding_model_version is None
            and chunk.embedding_dimensions is None
            and chunk.embedding_chunk_hash is None
            for chunk in stale
        )
        assert not any(chunk.document_version_id == rejected_version for chunk in chunks)
        active = [chunk for chunk in chunks if chunk.active]
        assert active and {chunk.document_version_id for chunk in active} == {replacement_version}
        assert all(
            chunk.embedding_status == "READY" and chunk.embedding is not None for chunk in active
        )
        assert all(chunk.source_type == "xlsx" and chunk.page_number is None for chunk in active)
        assert all(
            chunk.sheet_name is not None
            and chunk.row_start is not None
            and chunk.row_end is not None
            and chunk.cell_start is not None
            and chunk.cell_end is not None
            for chunk in active
        )
        metrics = next(chunk for chunk in active if "EBITDA Margin" in chunk.content)
        assert metrics.sheet_name == "Metrics"
        assert metrics.row_start <= 5 <= metrics.row_end  # type: ignore[operator]

    searched = await _search(auth_harness.client, alice, "EBITDA Margin")
    assert searched.status_code == 200
    results = searched.json()["data"]["results"]
    assert results
    assert {item["document_version_id"] for item in results} == {str(replacement_version)}
    assert all(item["source"]["sheet_name"] is not None for item in results)


@pytest.mark.asyncio
async def test_demo_user_search_matrix_and_forged_request_values_fail_closed(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    specs = (
        (
            "orion/finance/Orion_FY2025_Board_Pack.pdf",
            "orion",
            "finance",
            "FINANCIAL_REPORT",
            "FY2025",
        ),
        (
            "orion/legal/Orion_Series_C_Investment_Agreement.pdf",
            "orion",
            "legal",
            "LEGAL_AGREEMENT",
            "2026",
        ),
        (
            "orion/shared/Orion_Company_Profile.pdf",
            "orion",
            "shared",
            "OTHER",
            None,
        ),
        (
            "atlas/finance/Atlas_FY2025_Board_Pack.pdf",
            "atlas",
            "finance",
            "FINANCIAL_REPORT",
            "FY2025",
        ),
        (
            "atlas/legal/Atlas_Credit_Facility_Agreement.pdf",
            "atlas",
            "legal",
            "LEGAL_AGREEMENT",
            "2026",
        ),
        (
            "atlas/shared/Atlas_Company_Profile.pdf",
            "atlas",
            "shared",
            "OTHER",
            None,
        ),
    )
    for index, (path, workspace, department, document_type, period) in enumerate(specs):
        await _upload_and_approve(
            auth_harness.client,
            nora,
            relative_path=path,
            media_type="application/pdf",
            metadata=_metadata(
                workspace=workspace,
                department=department,
                document_type=document_type,
                reporting_period=period,
            ),
            idempotency_key=f"search-matrix-{index:04d}",
        )

    matrix = {
        "alice@example.com": ("orion", {"finance", "shared"}),
        "leo@example.com": ("orion", {"legal", "shared"}),
        "maya@example.com": ("orion", {"finance", "legal", "shared"}),
        "amir@example.com": ("atlas", {"finance", "shared"}),
        "lina@example.com": ("atlas", {"legal", "shared"}),
    }
    for email, (tenant, departments) in matrix.items():
        token = await _login(auth_harness.client, email)
        response = await _search(auth_harness.client, token, "synthetic")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["results"]
        assert data["status"] == "ready"
        assert data["indexing"]["embedding"]["status"] == "ready"
        assert data["indexing"]["embedding"]["dimensions"] == 768
        assert data["evaluation_summary"] == {"status": "not_run"}
        for item in data["results"]:
            assert set(item["scores"]) == {"keyword", "vector", "final"}
            assert all(0 <= score <= 1 for score in item["scores"].values())
            assert item["citation"]["chunk_id"] == item["chunk_id"]
            assert item["citation"]["document_id"] == item["document_id"]
            assert item["citation"]["document_version_id"] == item["document_version_id"]
            assert item["citation"]["excerpt"] == item["excerpt"]
        assert {item["document"]["tenant_slug"] for item in data["results"]} == {tenant}
        assert {item["document"]["department"] for item in data["results"]} <= departments
        assert {grant["workspace"]["slug"] for grant in data["authorized_scope"]["grants"]} == {
            tenant
        }

    nora_denied = await _search(auth_harness.client, nora, "synthetic")
    assert nora_denied.status_code == 403
    assert nora_denied.json()["error"] == {
        "code": "forbidden",
        "message": "Document search is not permitted.",
    }

    alice = await _login(auth_harness.client, "alice@example.com")
    forged_extra_body = await auth_harness.client.post(
        "/api/development/authorized-search",
        headers={"Authorization": f"Bearer {alice}"},
        json={
            "query": "termination",
            "top_k": 20,
            "tenant_id": str(seed_id("tenant", "atlas")),
            "company_id": str(seed_id("company", "atlas-main")),
            "department": "legal",
            "role": "admin",
            "user_id": str(seed_id("user", "nora")),
            "document_id": str(seed_id("document", "unknown")),
            "version_id": str(seed_id("version", "unknown")),
        },
    )
    assert forged_extra_body.status_code == 422
    assert forged_extra_body.json()["error"]["code"] == "validation_error"

    ignored_headers_and_query = await auth_harness.client.post(
        "/api/development/authorized-search?tenant_id=atlas&department=legal&role=admin",
        headers={
            "Authorization": f"Bearer {alice}",
            "X-Tenant-ID": str(seed_id("tenant", "atlas")),
            "X-User-ID": str(seed_id("user", "nora")),
            "X-Role": "admin",
        },
        json={"query": "termination", "top_k": 20},
    )
    assert ignored_headers_and_query.status_code == 200
    ignored_results = ignored_headers_and_query.json()["data"]["results"]
    assert all(item["document"]["tenant_slug"] == "orion" for item in ignored_results)
    assert all(item["document"]["department"] in {"finance", "shared"} for item in ignored_results)


@pytest.mark.asyncio
async def test_query_and_top_k_limits_are_strict_and_normalization_is_bounded(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    headers = {"Authorization": f"Bearer {alice}"}
    invalid_payloads: tuple[dict[str, object], ...] = (
        {"query": "", "top_k": 5},
        {"query": "   ", "top_k": 5},
        {"query": "x" * 501, "top_k": 5},
        {"query": "revenue", "top_k": 0},
        {"query": "revenue", "top_k": 21},
        {"query": "revenue", "top_k": "5"},
        {"query": "revenue", "top_k": 5, "unexpected": True},
    )
    for payload in invalid_payloads:
        response = await auth_harness.client.post(
            "/api/development/authorized-search", headers=headers, json=payload
        )
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "validation_error"

    normalized = await auth_harness.client.post(
        "/api/development/authorized-search",
        headers=headers,
        json={"query": "  revenue\n\t growth  ", "top_k": 1},
    )
    assert normalized.status_code == 200
    assert normalized.json()["data"]["query"] == "revenue growth"
    assert normalized.json()["data"]["top_k"] == 1


@pytest.mark.asyncio
async def test_bounded_reindex_backfills_only_manageable_current_approved_chunks(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    document = await _upload_and_approve(
        auth_harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="FINANCIAL_REPORT",
            reporting_period="FY2025",
        ),
        idempotency_key="embedding-backfill-0001",
    )
    document_id = UUID(str(document["id"]))
    async with auth_harness.session_factory() as session:
        await session.execute(
            update(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .values(
                embedding=None,
                embedding_model_name=None,
                embedding_model_version=None,
                embedding_dimensions=None,
                embedding_chunk_hash=None,
                embedding_status="PENDING",
            )
        )
        await session.commit()
        pending_count = len(
            tuple(
                (
                    await session.execute(
                        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
                    )
                ).scalars()
            )
        )

    before = await _search(auth_harness.client, alice, "Margin Compression")
    assert before.status_code == 200
    assert before.json()["data"]["results"] == []
    denied = await auth_harness.client.post(
        "/api/development/reindex-embeddings",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert denied.status_code == 403
    auth_harness.settings.embedding_max_chunks = 1
    processed = 0
    for _ in range(pending_count):
        reindexed = await auth_harness.client.post(
            "/api/development/reindex-embeddings",
            headers={"Authorization": f"Bearer {nora}"},
        )
        assert reindexed.status_code == 200, reindexed.text
        assert reindexed.json()["data"]["processed_chunk_count"] == 1
        processed += 1
    assert processed == pending_count
    after = await _search(auth_harness.client, alice, "Margin Compression")
    assert after.status_code == 200
    assert after.json()["data"]["results"]
    async with auth_harness.session_factory() as session:
        rows = tuple(
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
            ).scalars()
        )
        assert rows and all(
            row.embedding_status == "READY"
            and row.embedding is not None
            and row.embedding_model_name == "nomic-embed-text"
            and row.embedding_model_version == "v1.5"
            and row.embedding_dimensions == 768
            and row.embedding_chunk_hash == row.content_hash
            for row in rows
        )


@pytest.mark.asyncio
async def test_corrupted_copied_acl_is_excluded_from_search_and_reindex(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    document = await _upload_and_approve(
        auth_harness.client,
        nora,
        relative_path="orion/legal/Orion_Series_C_Investment_Agreement.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="legal",
            document_type="LEGAL_AGREEMENT",
            reporting_period="2026",
        ),
        idempotency_key="embedding-corrupt-acl-0001",
    )
    document_id = UUID(str(document["id"]))
    async with auth_harness.session_factory() as session:
        await session.execute(
            update(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .values(
                department="finance",
                visibility="DEPARTMENT_PRIVATE",
                classification="FINANCE_ONLY",
                embedding=None,
                embedding_model_name=None,
                embedding_model_version=None,
                embedding_dimensions=None,
                embedding_chunk_hash=None,
                embedding_status="PENDING",
            )
        )
        await session.commit()

    searched = await _search(auth_harness.client, alice, "investment agreement")
    assert searched.status_code == 200
    assert searched.json()["data"]["results"] == []
    reindexed = await auth_harness.client.post(
        "/api/development/reindex-embeddings",
        headers={"Authorization": f"Bearer {nora}"},
    )
    assert reindexed.status_code == 200
    assert reindexed.json()["data"]["processed_chunk_count"] == 0
    async with auth_harness.session_factory() as session:
        statuses = tuple(
            (
                await session.execute(
                    select(DocumentChunk.embedding_status).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            ).scalars()
        )
        assert statuses and set(statuses) == {"PENDING"}


@pytest.mark.asyncio
async def test_model_name_and_tag_mismatch_are_excluded_from_hybrid_ranking(
    auth_harness: AuthHarness,
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    document = await _upload_and_approve(
        auth_harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="FINANCIAL_REPORT",
            reporting_period="FY2025",
        ),
        idempotency_key="embedding-model-mismatch-0001",
    )
    document_id = UUID(str(document["id"]))
    async with auth_harness.session_factory() as session:
        chunks = tuple(
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.ordinal)
                    .limit(2)
                )
            ).scalars()
        )
        assert len(chunks) == 2
        chunks[0].embedding_model_name = "wrong-model"
        chunks[1].embedding_model_version = "wrong-tag"
        mismatched_ids = {str(item.id) for item in chunks}
        await session.commit()

    searched = await _search(auth_harness.client, alice, "synthetic")
    assert searched.status_code == 200
    assert mismatched_ids.isdisjoint(
        {item["chunk_id"] for item in searched.json()["data"]["results"]}
    )


class _FailingEmbeddingProvider(DeterministicFakeEmbeddingProvider):
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise EmbeddingProviderError("secret query /internal/path", transient=True)


@pytest.mark.asyncio
async def test_failed_approval_rolls_back_and_retry_is_idempotent(
    auth_harness: AuthHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    nora = await _login(auth_harness.client, "nora@example.com")
    uploaded = await _upload(
        auth_harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="FINANCIAL_REPORT",
            reporting_period="FY2025",
        ),
        idempotency_key="embedding-retry-approval-0001",
    )
    assert uploaded.status_code == 201
    document = uploaded.json()["data"]["document"]
    document_id = UUID(document["id"])
    version_id = UUID(document["version"]["id"])
    monkeypatch.setattr(
        document_routes,
        "create_embedding_provider",
        lambda settings: _FailingEmbeddingProvider(),
    )
    failed = await _approve(auth_harness.client, nora, document)
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "embedding_unavailable"
    async with auth_harness.session_factory() as session:
        stored_document = await session.get(Document, document_id)
        stored_version = await session.get(DocumentVersion, version_id)
        chunk_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.document_version_id == version_id)
                )
            ).scalar_one()
        )
        failure_event = (
            (
                await session.execute(
                    select(DocumentAuditEvent)
                    .where(DocumentAuditEvent.event_type == "document_chunk_index")
                    .order_by(DocumentAuditEvent.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .one()
        )
        assert stored_document is not None and stored_document.current_approved_version_id is None
        assert stored_version is not None and stored_version.status == "PREVIEW_READY"
        assert chunk_count == 0
        assert failure_event.reason_code == "UNKNOWN_PROVIDER_ERROR"
        assert "secret" not in json.dumps(failure_event.event_metadata)

    monkeypatch.setattr(
        document_routes,
        "create_embedding_provider",
        lambda settings: DeterministicFakeEmbeddingProvider(),
    )
    retried = await _approve(auth_harness.client, nora, document)
    assert retried.status_code == 200
    async with auth_harness.session_factory() as session:
        ready = tuple(
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
                )
            ).scalars()
        )
        assert ready and all(
            item.active and item.embedding_status == "READY" and item.embedding is not None
            for item in ready
        )
