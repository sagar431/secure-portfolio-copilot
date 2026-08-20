import inspect
from typing import get_type_hints
from uuid import uuid4

import pytest

from app.policies.models import AuthorizationScope, TrustedIdentity
from app.retrieval import repository


@pytest.mark.parametrize(
    "method",
    [
        repository.search_authorized_chunks,
        repository.get_authorized_index_status,
    ],
)
def test_every_public_retrieval_repository_method_requires_authorization_scope(
    method: object,
) -> None:
    signature = inspect.signature(method)

    assert "scope" in signature.parameters
    assert signature.parameters["scope"].default is inspect.Parameter.empty
    assert get_type_hints(method)["scope"] is AuthorizationScope


def test_unscoped_repository_calls_are_not_callable() -> None:
    with pytest.raises(TypeError):
        repository.search_authorized_chunks(  # type: ignore[call-arg]
            object(), query="revenue", top_k=5
        )
    with pytest.raises(TypeError):
        repository.get_authorized_index_status(object())  # type: ignore[call-arg]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vector",
    [
        (1.0,) * 767,
        (float("nan"),) + (0.0,) * 767,
        (float("inf"),) + (0.0,) * 767,
        (0.0,) * 768,
    ],
)
async def test_repository_rejects_invalid_query_vectors_before_database_execution(
    vector: tuple[float, ...],
) -> None:
    identity = TrustedIdentity(user_id=uuid4(), email="alice@example.com", display_name="Alice")
    scope = AuthorizationScope(identity=identity, grants=())

    with pytest.raises(ValueError):
        await repository.search_authorized_chunks(
            object(),  # type: ignore[arg-type]
            scope,
            query="revenue",
            query_embedding=vector,
            model_name="nomic-embed-text",
            model_version="v1.5",
            dimensions=768,
            top_k=5,
        )
