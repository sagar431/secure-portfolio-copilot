from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.embeddings.contracts import EmbeddingErrorCode, EmbeddingProviderError
from app.main import create_app
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)
from app.retrieval.repository import search_authorized_chunks


def _settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "jwt_secret_key": SecretStr(
            "embedding-security-test-key-with-at-least-thirty-two-characters"
        ),
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("provider", ["ollama", "fake"])
def test_development_embedding_providers_are_rejected_in_production(provider: str) -> None:
    with pytest.raises(ValidationError, match="unavailable in production"):
        _settings(app_env="production", embedding_provider=provider)

    production = _settings(app_env="production", embedding_provider="disabled")

    assert production.embedding_provider == "disabled"


def test_production_application_excludes_all_development_embedding_routes() -> None:
    application = create_app(_settings(app_env="production", embedding_provider="disabled"))

    route_paths = set(application.openapi()["paths"])

    assert "/api/development/authorized-search" not in route_paths
    assert "/api/development/reindex-embeddings" not in route_paths


@pytest.mark.parametrize(
    "base_url",
    [
        "https://localhost:11434",
        "http://localhost.attacker.invalid:11434",
        "http://127.0.0.1.attacker.invalid:11434",
        "http://user:password@localhost:11434",
        "http://localhost:11434?target=attacker.invalid",
        "http://localhost:11434#attacker.invalid",
        "http://192.0.2.10:11434",
    ],
)
def test_ollama_base_url_rejects_nonlocal_or_ambiguous_targets(base_url: str) -> None:
    with pytest.raises(ValidationError, match="local development service"):
        _settings(ollama_base_url=base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
    ],
)
def test_ollama_base_url_accepts_only_explicit_http_loopback_targets(base_url: str) -> None:
    assert _settings(ollama_base_url=base_url).ollama_base_url == base_url


def test_embedding_provider_error_never_renders_its_reason_code() -> None:
    sensitive_code = "UPSTREAM_BODY: query document-content /private/path"

    error = EmbeddingProviderError(sensitive_code, transient=True)

    assert str(error) == "Embedding provider is unavailable."
    assert sensitive_code not in str(error)
    assert sensitive_code not in repr(error)
    assert error.code is EmbeddingErrorCode.UNKNOWN_PROVIDER_ERROR
    assert error.transient is True


class _EmptyRows:
    def all(self) -> list[object]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statement: object | None = None

    async def execute(self, statement: object) -> _EmptyRows:
        self.statement = statement
        return _EmptyRows()


def _query_scope() -> AuthorizationScope:
    identity = TrustedIdentity(
        user_id=uuid4(),
        email="security-auditor@example.com",
        display_name="Security Auditor",
    )
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
                company_slugs=("company",),
                departments=(
                    DepartmentAccess(
                        key="finance",
                        source=GrantSource.PRIMARY_DEPARTMENT,
                    ),
                ),
                capabilities=(Capability.QUERY_DOCUMENTS,),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_hybrid_sql_materializes_authorized_rows_before_vector_ranking() -> None:
    session = _CapturingSession()

    results = await search_authorized_chunks(  # type: ignore[arg-type]
        session,
        _query_scope(),
        query="authorized query",
        query_embedding=(1.0,) + (0.0,) * 767,
        model_name="nomic-embed-text",
        model_version="v1.5",
        dimensions=768,
        top_k=5,
    )

    assert results == ()
    assert session.statement is not None
    sql = str(
        session.statement.compile(  # type: ignore[union-attr]
            dialect=postgresql.dialect(),
        )
    )
    normalized_sql = " ".join(sql.split())
    assert "WITH authorized_chunks AS MATERIALIZED" in normalized_sql
    assert "authorized_chunks.embedding <=>" in normalized_sql
    assert normalized_sql.index("AS MATERIALIZED") < normalized_sql.index(
        "authorized_chunks.embedding <=>"
    )
    assert "document_chunks.embedding <=>" not in normalized_sql
    assert "departments.key = document_chunks.department" in normalized_sql
    assert "documents.visibility = document_chunks.visibility" in normalized_sql
    assert "documents.classification = document_chunks.classification" in normalized_sql
