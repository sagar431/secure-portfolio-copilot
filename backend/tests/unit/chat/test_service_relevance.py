from types import SimpleNamespace
from typing import cast

from app.chat.service import _sufficient_results
from app.schemas.retrieval import AuthorizedSearchResultData


def _result(*, keyword: float, vector: float) -> AuthorizedSearchResultData:
    return cast(
        AuthorizedSearchResultData,
        SimpleNamespace(scores=SimpleNamespace(keyword=keyword, vector=vector)),
    )


def test_lexical_matches_exclude_semantic_noise_from_grounding_and_routing() -> None:
    lexical = _result(keyword=0.1, vector=0.6)
    semantic_noise = _result(keyword=0.0, vector=0.9)

    assert _sufficient_results((semantic_noise, lexical)) == (lexical,)


def test_semantic_results_remain_available_when_there_are_no_lexical_matches() -> None:
    relevant = _result(keyword=0.0, vector=0.6)
    too_distant = _result(keyword=0.0, vector=0.2)

    assert _sufficient_results((relevant, too_distant)) == (relevant,)
