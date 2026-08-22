import re
from dataclasses import dataclass
from enum import StrEnum


class ModelRoute(StrEnum):
    SIMPLE = "simple"
    HEAVY = "heavy"


class WorkloadKind(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    AGENTIC = "agentic"


class ResponseMode(StrEnum):
    FAST = "fast"
    AUTO = "auto"
    DEEP = "deep"


class RouteReason(StrEnum):
    USER_REQUESTED_DEEP = "USER_REQUESTED_DEEP"
    FAST_MODE_ELIGIBLE = "FAST_MODE_ELIGIBLE"
    DEEP_MODE_REQUIRED = "DEEP_MODE_REQUIRED"
    SIMPLE_LOW_RISK = "SIMPLE_LOW_RISK"
    AGENTIC_REQUEST = "AGENTIC_REQUEST"
    MULTI_DOCUMENT = "MULTI_DOCUMENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    COMPLEX_REQUEST = "COMPLEX_REQUEST"


@dataclass(frozen=True, slots=True)
class RoutingSignals:
    workload: WorkloadKind
    question: str
    authorized_document_count: int
    top_retrieval_score: float | None


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    route: ModelRoute
    reason: RouteReason
    requested_response_mode: ResponseMode
    resolved_response_mode: ResponseMode
    upgrade_required: bool = False


_COMPLEX_TERMS = re.compile(
    r"\b(compare|comparison|versus|vs\.?|across|trend|trends|why|drivers?|"
    r"conflict|conflicting|synthesi[sz]e|scenario|sensitivity|multi[- ]document)\b",
    re.IGNORECASE,
)
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")
_METRIC = re.compile(
    r"\b(revenue|ebitda|margin|profit|cash|debt|growth|cagr|runway)\b",
    re.IGNORECASE,
)


def _is_complex(question: str) -> bool:
    normalized = " ".join(question.split())
    if _COMPLEX_TERMS.search(normalized):
        return True
    return len(set(_PERIOD.findall(normalized))) > 1 and len(_METRIC.findall(normalized)) > 1


def _automatic_route(
    signals: RoutingSignals, *, low_confidence_threshold: float
) -> tuple[ModelRoute, RouteReason]:
    if signals.workload is WorkloadKind.AGENTIC:
        return ModelRoute.HEAVY, RouteReason.AGENTIC_REQUEST
    if signals.authorized_document_count > 1:
        return ModelRoute.HEAVY, RouteReason.MULTI_DOCUMENT
    if (
        signals.top_retrieval_score is None
        or signals.top_retrieval_score < low_confidence_threshold
    ):
        return ModelRoute.HEAVY, RouteReason.LOW_CONFIDENCE
    if _is_complex(signals.question):
        return ModelRoute.HEAVY, RouteReason.COMPLEX_REQUEST
    return ModelRoute.SIMPLE, RouteReason.SIMPLE_LOW_RISK


def route_model(
    signals: RoutingSignals,
    *,
    low_confidence_threshold: float,
    response_mode: ResponseMode = ResponseMode.AUTO,
) -> RoutingDecision:
    """Choose a model from host-owned signals; never identity or authorization claims."""

    automatic_route, automatic_reason = _automatic_route(
        signals, low_confidence_threshold=low_confidence_threshold
    )
    if response_mode is ResponseMode.DEEP:
        return RoutingDecision(
            ModelRoute.HEAVY,
            RouteReason.USER_REQUESTED_DEEP,
            response_mode,
            ResponseMode.DEEP,
        )
    if response_mode is ResponseMode.FAST:
        if automatic_route is ModelRoute.SIMPLE:
            return RoutingDecision(
                ModelRoute.SIMPLE,
                RouteReason.FAST_MODE_ELIGIBLE,
                response_mode,
                ResponseMode.FAST,
            )
        return RoutingDecision(
            ModelRoute.HEAVY,
            RouteReason.DEEP_MODE_REQUIRED,
            response_mode,
            ResponseMode.DEEP,
            upgrade_required=True,
        )
    return RoutingDecision(
        automatic_route,
        automatic_reason,
        response_mode,
        ResponseMode.FAST if automatic_route is ModelRoute.SIMPLE else ResponseMode.DEEP,
    )
