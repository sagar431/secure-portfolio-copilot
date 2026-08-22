import json
from collections import Counter
from pathlib import Path

import pytest

from app.evaluations.contracts import EvaluationCategory
from app.evaluations.manifest import (
    DEFAULT_SUITE_VERSION,
    EXPECTED_COUNTS,
    ManifestError,
    load_manifest,
    manifest_hash,
)


def test_checked_in_manifest_has_exact_release_composition_and_stable_hash() -> None:
    manifest = load_manifest()

    assert manifest.version == DEFAULT_SUITE_VERSION
    assert len(manifest.cases) == 42
    assert len({case.id for case in manifest.cases}) == 42
    assert Counter(case.category for case in manifest.cases) == Counter(EXPECTED_COUNTS)
    assert len(manifest_hash()) == 64
    assert all(
        case.identity_key in {"nora", "alice", "leo", "maya", "amir", "lina"}
        for case in manifest.cases
    )


def test_manifest_covers_required_positive_sources_and_modalities() -> None:
    positive = [
        case
        for case in load_manifest().cases
        if case.category is EvaluationCategory.AUTHORIZED_POSITIVE
    ]
    identifiers = {item for case in positive for item in case.expected.document_ids}

    assert any(item.endswith("FIN-2025-001") for item in identifiers)
    assert any("FIN-PDF" in item for item in identifiers)
    assert {case.department for case in positive} >= {"finance", "legal", "shared"}
    assert {case.workspace_slug for case in positive} == {"orion", "atlas"}
    assert any(len(case.expected.document_ids) > 1 for case in positive)
    assert all(case.expected.citation_required for case in positive)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "count",
        "category",
        "unknown-document",
        "extra-field",
    ],
)
def test_loader_rejects_manifest_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    source = Path(__file__).parents[3] / "app/evaluations/manifests/v1.0.0.json"
    payload = json.loads(source.read_text())
    if mutation == "duplicate":
        payload["cases"][1]["id"] = payload["cases"][0]["id"]
    elif mutation == "count":
        payload["cases"].pop()
    elif mutation == "category":
        payload["cases"][0]["category"] = "explicit_denial"
    elif mutation == "unknown-document":
        payload["cases"][0]["expected"]["document_ids"] = ["NOT-CHECKED-IN"]
    else:
        payload["cases"][0]["prompt"] = "client controlled"
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(payload))
    monkeypatch.setattr("app.evaluations.manifest._path", lambda _: changed)
    load_manifest.cache_clear()
    try:
        with pytest.raises(ManifestError):
            load_manifest()
    finally:
        load_manifest.cache_clear()
