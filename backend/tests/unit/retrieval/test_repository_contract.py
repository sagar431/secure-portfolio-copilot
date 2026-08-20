import inspect
from typing import get_type_hints

import pytest

from app.policies.models import AuthorizationScope
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
