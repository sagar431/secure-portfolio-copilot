import json
from pathlib import Path

import pytest
from anyio import Path as AsyncPath
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.models.documents import DocumentAuditEvent, DocumentVersion, IngestionStatus
from app.scripts.seed_development import seed_id
from tests.conftest import DEMO_PASSWORD, AuthHarness

DATA_ROOT = Path(__file__).resolve().parents[3] / "Simulated_data"


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return str(response.json()["data"]["access_token"])


def _metadata(*, document_type: str, reporting_period: str) -> dict[str, str]:
    return {
        "tenant_id": str(seed_id("tenant", "orion")),
        "company_id": str(seed_id("company", "orion-main")),
        "department": "finance",
        "visibility": "DEPARTMENT_PRIVATE",
        "classification": "FINANCE_ONLY",
        "document_type": document_type,
        "reporting_period": reporting_period,
    }


async def _upload(
    client: AsyncClient,
    token: str,
    *,
    path: Path,
    media_type: str,
    metadata: dict[str, str],
    idempotency_key: str,
    endpoint: str = "/api/admin/documents",
) -> Response:
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


@pytest.mark.asyncio
async def test_nora_uploads_previews_approves_and_deletes_pdf(
    auth_harness: AuthHarness,
) -> None:
    token = await _login(auth_harness.client, "nora@example.com")
    path = DATA_ROOT / "orion/finance/Orion_FY2025_Board_Pack.pdf"
    response = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type="application/pdf",
        metadata=_metadata(document_type="FINANCIAL_REPORT", reporting_period="FY2025"),
        idempotency_key="pdf-flow-0001",
    )

    assert response.status_code == 201, response.text
    document = response.json()["data"]["document"]
    document_id = document["id"]
    version_id = document["version"]["id"]
    job_id = document["ingestion_job_id"]
    assert document["version"]["status"] == "PREVIEW_READY"
    assert document["version"]["source_type"] == "PDF"
    assert document["version"]["page_count"] == 4

    options = await auth_harness.client.get(
        "/api/admin/ingestion/options", headers={"Authorization": f"Bearer {token}"}
    )
    assert options.status_code == 200
    option_data = options.json()["data"]
    assert {item["classification"] for item in option_data["classification_pairs"]} == {
        "FINANCE_ONLY",
        "LEGAL_ONLY_CONFIDENTIAL",
        "TENANT_SHARED",
    }
    assert option_data["limits"]["max_upload_bytes"] == 10 * 1024 * 1024

    preview = await auth_harness.client.get(
        f"/api/admin/documents/{document_id}/versions/{version_id}/preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert preview.status_code == 200
    assert [page["page_number"] for page in preview.json()["data"]["pages"]] == [1, 2, 3, 4]

    status = await auth_harness.client.get(
        f"/api/admin/ingestion/{job_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert status.status_code == 200
    assert status.json()["data"]["status"] == "PREVIEW_READY"

    alice = await _login(auth_harness.client, "alice@example.com")
    denied_approval = await auth_harness.client.post(
        f"/api/admin/documents/{document_id}/versions/{version_id}/approve",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert denied_approval.status_code == 404

    approved = await auth_harness.client.post(
        f"/api/admin/documents/{document_id}/versions/{version_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["current_approved_version_id"] == version_id
    repeated_approval = await auth_harness.client.post(
        f"/api/admin/documents/{document_id}/versions/{version_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert repeated_approval.status_code == 409

    library = await auth_harness.client.get(
        "/api/admin/documents", headers={"Authorization": f"Bearer {token}"}
    )
    assert library.status_code == 200
    assert library.json()["data"]["items"][0]["id"] == document_id

    deleted = await auth_harness.client.delete(
        f"/api/admin/documents/{document_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "DELETED"
    unavailable = await auth_harness.client.get(
        f"/api/admin/documents/{document_id}/versions/{version_id}/preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unavailable.status_code == 404


@pytest.mark.asyncio
async def test_initial_checksum_dedupes_but_explicit_reupload_creates_version(
    auth_harness: AuthHarness,
) -> None:
    token = await _login(auth_harness.client, "nora@example.com")
    path = DATA_ROOT / "orion/finance/Orion_FY2024_FY2025_Financials.xlsx"
    metadata = _metadata(document_type="SPREADSHEET", reporting_period="FY2024-FY2025")
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    first = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type=media_type,
        metadata=metadata,
        idempotency_key="xlsx-flow-0001",
    )
    assert first.status_code == 201, first.text
    first_document = first.json()["data"]["document"]
    assert first_document["version"]["source_type"] == "XLSX"

    approved = await auth_harness.client.post(
        f"/api/admin/documents/{first_document['id']}/versions/"
        f"{first_document['version']['id']}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200

    duplicate = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type=media_type,
        metadata=metadata,
        idempotency_key="xlsx-flow-0002",
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["deduplicated"] is True
    assert duplicate.json()["data"]["document"]["version"]["id"] == first_document["version"]["id"]

    explicit = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type=media_type,
        metadata=metadata,
        idempotency_key="xlsx-flow-0003",
        endpoint=f"/api/admin/documents/{first_document['id']}/versions",
    )
    assert explicit.status_code == 201, explicit.text
    explicit_document = explicit.json()["data"]["document"]
    assert explicit_document["id"] == first_document["id"]
    assert explicit_document["version"]["version_number"] == 2
    assert explicit_document["version"]["id"] != first_document["version"]["id"]

    replay = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type=media_type,
        metadata=metadata,
        idempotency_key="xlsx-flow-0003",
        endpoint=f"/api/admin/documents/{first_document['id']}/versions",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["deduplicated"] is True
    assert replay.json()["data"]["document"]["version"]["id"] == explicit_document["version"]["id"]

    conflict = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type="application/octet-stream",
        metadata=metadata,
        idempotency_key="xlsx-flow-0003",
        endpoint=f"/api/admin/documents/{first_document['id']}/versions",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    preview = await auth_harness.client.get(
        f"/api/admin/documents/{explicit_document['id']}/versions/"
        f"{explicit_document['version']['id']}/preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert preview.status_code == 200
    sheets = preview.json()["data"]["sheets"]
    assert sheets
    assert sheets[0]["rows"][0]["cells"][0]["coordinate"]

    rejected = await auth_harness.client.post(
        f"/api/admin/documents/{explicit_document['id']}/versions/"
        f"{explicit_document['version']['id']}/reject",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["current_approved_version_id"] == first_document["version"]["id"]

    rejected_library = await auth_harness.client.get(
        "/api/admin/documents?status=REJECTED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected_library.status_code == 200
    assert rejected_library.json()["data"]["items"][0]["version"]["status"] == "REJECTED"
    approved_library = await auth_harness.client.get(
        "/api/admin/documents?status=APPROVED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved_library.status_code == 200
    assert approved_library.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_non_admin_denied_before_document_operations(auth_harness: AuthHarness) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    path = DATA_ROOT / "orion/finance/Orion_FY2025_Board_Pack.pdf"

    options = await auth_harness.client.get(
        "/api/admin/ingestion/options", headers={"Authorization": f"Bearer {alice}"}
    )
    assert options.status_code == 403
    upload = await _upload(
        auth_harness.client,
        alice,
        path=path,
        media_type="application/pdf",
        metadata=_metadata(document_type="FINANCIAL_REPORT", reporting_period="FY2025"),
        idempotency_key="alice-deny-0001",
    )
    assert upload.status_code == 403


@pytest.mark.asyncio
async def test_invalid_file_persists_safe_validation_failed_state_and_audit(
    auth_harness: AuthHarness,
) -> None:
    token = await _login(auth_harness.client, "nora@example.com")
    path = DATA_ROOT / "invalid_inputs/not_a_real_pdf.pdf"
    response = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type="application/pdf",
        metadata=_metadata(document_type="FINANCIAL_REPORT", reporting_period="FY2025"),
        idempotency_key="invalid-pdf-0001",
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_document"

    replay = await _upload(
        auth_harness.client,
        token,
        path=path,
        media_type="application/pdf",
        metadata=_metadata(document_type="FINANCIAL_REPORT", reporting_period="FY2025"),
        idempotency_key="invalid-pdf-0001",
    )
    assert replay.status_code == response.status_code
    assert replay.json()["error"] == response.json()["error"]

    async with auth_harness.session_factory() as session:
        versions = (
            (
                await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.idempotency_key == "invalid-pdf-0001"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(versions) == 1
        version = versions[0]
        assert version.status == IngestionStatus.VALIDATION_FAILED
        assert version.storage_key is None
        events = (
            (
                await session.execute(
                    select(DocumentAuditEvent).where(
                        DocumentAuditEvent.document_version_id == version.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [(event.event_type, event.outcome, event.reason_code) for event in events] == [
            ("document_validate", "error", "INVALID_FILE_SIGNATURE"),
            ("document_upload", "error", "IDEMPOTENT_FAILURE_REPLAY"),
        ]

    library = await auth_harness.client.get(
        "/api/admin/documents?status=VALIDATION_FAILED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert library.status_code == 200
    failed_document = library.json()["data"]["items"][0]
    assert failed_document["version"]["source_type"] == "UNKNOWN"
    failed_status = await auth_harness.client.get(
        f"/api/admin/ingestion/{failed_document['ingestion_job_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert failed_status.status_code == 200
    assert failed_status.json()["data"]["status"] == "VALIDATION_FAILED"
    assert failed_status.json()["data"]["safe_error_code"] == "INVALID_FILE_SIGNATURE"


@pytest.mark.asyncio
async def test_invalid_metadata_fixture_is_rejected_before_ingestion(
    auth_harness: AuthHarness,
) -> None:
    token = await _login(auth_harness.client, "nora@example.com")
    descriptor = json.loads(
        (DATA_ROOT / "invalid_inputs/invalid_metadata.json").read_text(encoding="utf-8")
    )
    response = await _upload(
        auth_harness.client,
        token,
        path=DATA_ROOT / "orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=descriptor,
        idempotency_key="invalid-metadata-0001",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_document_metadata"
    async with auth_harness.session_factory() as session:
        versions = (
            (
                await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.idempotency_key == "invalid-metadata-0001"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert versions == []
