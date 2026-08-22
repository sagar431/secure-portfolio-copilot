from datetime import UTC, datetime

from app.evaluations.contracts import EvaluationCaseStatus, SafeCaseResult
from app.evaluations.manifest import load_manifest
from app.evaluations.scorers import (
    aggregate_metrics,
    has_authorization_leak,
    percentile_95,
    release_gates,
    score_exact,
    score_identifier_membership,
)


def _result(case: object) -> SafeCaseResult:
    now = datetime.now(UTC)
    expected = case.expected.document_ids  # type: ignore[attr-defined]
    citation = case.expected.citation_required  # type: ignore[attr-defined]
    return SafeCaseResult(
        case_id=case.id,  # type: ignore[attr-defined]
        category=case.category,  # type: ignore[attr-defined]
        status=EvaluationCaseStatus.PASS,
        reason_code=case.expected.reason_code,  # type: ignore[attr-defined]
        expected_identifiers=expected or case.expected.memory_ids,  # type: ignore[attr-defined]
        actual_identifiers=expected,
        metrics={
            "citation_present": citation,
            "citation_count": len(expected) if citation else 0,
            "supported_citations": len(expected) if citation else 0,
        },
        duration_ms=10,
        started_at=now,
        completed_at=now,
    )


def test_deterministic_scorers_and_release_thresholds() -> None:
    assert score_identifier_membership(("a", "b"), ("a", "b"), ("secret",)) == (1.0, 1.0, False)
    assert score_identifier_membership(("a",), ("secret",), ("secret",))[2]
    assert score_exact(10.0, 10.000001, 0.00001)
    assert not score_exact(10.0, None, 0.1)
    assert percentile_95(tuple(range(1, 101))) == 95

    manifest = load_manifest()
    results = tuple(_result(case) for case in manifest.cases)
    metrics = aggregate_metrics(manifest.cases, results)
    gates = release_gates(metrics)

    assert metrics.total == metrics.passed == 42
    assert metrics.cross_tenant_deny_pass_rate == 1.0
    assert metrics.cross_department_deny_pass_rate == 1.0
    assert metrics.memory_isolation_pass_rate == 1.0
    assert metrics.calculation_exactness == 1.0
    assert metrics.retrieval_recall_at_5 == 1.0
    assert all(gate.passed for gate in gates)
    assert not has_authorization_leak(manifest.cases, results)


def test_one_forbidden_identifier_is_a_security_leak() -> None:
    manifest = load_manifest()
    case = next(item for item in manifest.cases if item.expected.forbidden_document_ids)
    result = _result(case).model_copy(
        update={"actual_identifiers": (case.expected.forbidden_document_ids[0],)}
    )

    assert has_authorization_leak(manifest.cases, (result,))
