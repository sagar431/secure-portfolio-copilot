from __future__ import annotations

import math
from collections import Counter

from app.evaluations.contracts import (
    EvaluationCase,
    EvaluationCaseStatus,
    EvaluationCategory,
    EvaluationMetrics,
    ReleaseGate,
    SafeCaseResult,
)

RELEASE_THRESHOLDS = {
    "cross_tenant_denial": 1.0,
    "cross_department_denial": 1.0,
    "memory_isolation": 1.0,
    "calculation_exactness": 1.0,
    "citation_presence": 1.0,
    "retrieval_recall_at_5": 0.9,
    "citation_support_precision": 0.9,
    "abstention_correctness": 0.9,
}


def ratio(passed: int, total: int) -> float:
    return 1.0 if total == 0 else passed / total


def percentile_95(values: tuple[int, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)])


def score_identifier_membership(
    expected: tuple[str, ...], actual: tuple[str, ...], forbidden: tuple[str, ...]
) -> tuple[float, float, bool]:
    actual_set = set(actual)
    expected_set = set(expected)
    recall = ratio(len(expected_set & actual_set), len(expected_set))
    precision = ratio(len(expected_set & actual_set), len(actual_set))
    leaked = bool(actual_set.intersection(forbidden))
    return recall, precision, leaked


def score_exact(expected: float, actual: float | None, tolerance: float) -> bool:
    return actual is not None and math.isfinite(actual) and abs(actual - expected) <= tolerance


def aggregate_metrics(
    cases: tuple[EvaluationCase, ...], results: tuple[SafeCaseResult, ...]
) -> EvaluationMetrics:
    by_id = {result.case_id: result for result in results}
    passed = sum(result.status is EvaluationCaseStatus.PASS for result in results)
    failed = sum(result.status is EvaluationCaseStatus.FAIL for result in results)
    errors = sum(result.status is EvaluationCaseStatus.ERROR for result in results)

    def subset_rate(predicate: object) -> float:
        selected = [case for case in cases if predicate(case)]  # type: ignore[operator]
        return ratio(
            sum(
                by_id.get(case.id) is not None
                and by_id[case.id].status is EvaluationCaseStatus.PASS
                for case in selected
            ),
            len(selected),
        )

    cross_tenant = subset_rate(
        lambda case: (
            case.category is EvaluationCategory.EXPLICIT_DENIAL
            and case.expected.reason_code == "DENY_WORKSPACE"
        )
    )
    cross_department = subset_rate(
        lambda case: (
            case.category is EvaluationCategory.EXPLICIT_DENIAL
            and case.expected.reason_code == "DENY_DEPARTMENT"
        )
    )
    memory_isolation = subset_rate(
        lambda case: case.category is EvaluationCategory.MEMORY_ISOLATION
    )
    calculations = subset_rate(
        lambda case: case.category is EvaluationCategory.DETERMINISTIC_CALCULATION
    )
    abstentions = subset_rate(
        lambda case: case.category is EvaluationCategory.INSUFFICIENT_EVIDENCE
    )
    factual = [case for case in cases if case.expected.citation_required]
    citation_presence = ratio(
        sum(
            bool(by_id.get(case.id) and by_id[case.id].metrics.get("citation_present"))
            for case in factual
        ),
        len(factual),
    )
    retrieval_cases = [case for case in cases if case.expected.document_ids]
    total_expected = sum(len(case.expected.document_ids) for case in retrieval_cases)
    retrieved = sum(
        len(set(case.expected.document_ids).intersection(by_id[case.id].actual_identifiers))
        for case in retrieval_cases
        if case.id in by_id
    )
    citation_supported = sum(
        _integer_metric(by_id[case.id].metrics.get("supported_citations"))
        for case in factual
        if case.id in by_id
    )
    citation_total = sum(
        _integer_metric(by_id[case.id].metrics.get("citation_count"))
        for case in factual
        if case.id in by_id
    )
    route_counts = Counter(result.model_route for result in results if result.model_route)
    latencies = tuple(result.duration_ms for result in results)
    provider_cost = sum(result.cost_usd or 0.0 for result in results)
    return EvaluationMetrics(
        total=len(results),
        passed=passed,
        failed=failed,
        errors=errors,
        cross_tenant_deny_pass_rate=cross_tenant,
        cross_department_deny_pass_rate=cross_department,
        memory_isolation_pass_rate=memory_isolation,
        calculation_exactness=calculations,
        retrieval_recall_at_5=ratio(retrieved, total_expected),
        citation_presence_rate=citation_presence,
        citation_support_precision=ratio(citation_supported, citation_total),
        abstention_correctness=abstentions,
        average_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
        p95_latency_ms=percentile_95(latencies),
        input_tokens=sum(result.input_tokens or 0 for result in results),
        output_tokens=sum(result.output_tokens or 0 for result in results),
        provider_cost_usd=provider_cost,
        estimated_cost_usd=provider_cost,
        model_route_distribution=dict(sorted(route_counts.items())),
        fallback_count=sum(result.fallback_used for result in results),
        retry_count=sum(result.retry_count for result in results),
    )


def _integer_metric(value: float | int | bool | str | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def release_gates(metrics: EvaluationMetrics) -> tuple[ReleaseGate, ...]:
    values = {
        "cross_tenant_denial": metrics.cross_tenant_deny_pass_rate,
        "cross_department_denial": metrics.cross_department_deny_pass_rate,
        "memory_isolation": metrics.memory_isolation_pass_rate,
        "calculation_exactness": metrics.calculation_exactness,
        "citation_presence": metrics.citation_presence_rate,
        "retrieval_recall_at_5": metrics.retrieval_recall_at_5,
        "citation_support_precision": metrics.citation_support_precision,
        "abstention_correctness": metrics.abstention_correctness,
    }
    return tuple(
        ReleaseGate(
            name=name, value=values[name], threshold=threshold, passed=values[name] >= threshold
        )
        for name, threshold in RELEASE_THRESHOLDS.items()
    )


def has_authorization_leak(
    cases: tuple[EvaluationCase, ...], results: tuple[SafeCaseResult, ...]
) -> bool:
    by_id = {result.case_id: result for result in results}
    return any(
        set(by_id[case.id].actual_identifiers).intersection(case.expected.forbidden_document_ids)
        for case in cases
        if case.id in by_id
    )
