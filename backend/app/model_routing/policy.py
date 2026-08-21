import re
from dataclasses import dataclass
from enum import StrEnum


class ModelRoute(StrEnum):
    QWEN = "qwen"
    KIMI = "kimi"


class WorkloadKind(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    AGENTIC = "agentic"


class RouteReason(StrEnum):
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


def route_model(signals: RoutingSignals, *, low_confidence_threshold: float) -> RoutingDecision:
    """Choose a model from host-owned signals; never identity or authorization claims."""

    if signals.workload is WorkloadKind.AGENTIC:
        return RoutingDecision(ModelRoute.KIMI, RouteReason.AGENTIC_REQUEST)
    if signals.authorized_document_count > 1:
        return RoutingDecision(ModelRoute.KIMI, RouteReason.MULTI_DOCUMENT)
    if (
        signals.top_retrieval_score is None
        or signals.top_retrieval_score < low_confidence_threshold
    ):
        return RoutingDecision(ModelRoute.KIMI, RouteReason.LOW_CONFIDENCE)
    if _is_complex(signals.question):
        return RoutingDecision(ModelRoute.KIMI, RouteReason.COMPLEX_REQUEST)
    return RoutingDecision(ModelRoute.QWEN, RouteReason.SIMPLE_LOW_RISK)
