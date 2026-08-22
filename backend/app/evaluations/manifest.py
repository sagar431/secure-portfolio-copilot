from __future__ import annotations

import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from app.evaluations.contracts import EvaluationCategory, EvaluationManifest

DEFAULT_SUITE_VERSION = "1.0.0"
EXPECTED_COUNTS = {
    EvaluationCategory.AUTHORIZED_POSITIVE: 20,
    EvaluationCategory.EXPLICIT_DENIAL: 10,
    EvaluationCategory.MEMORY_ISOLATION: 4,
    EvaluationCategory.DETERMINISTIC_CALCULATION: 4,
    EvaluationCategory.INSUFFICIENT_EVIDENCE: 4,
}
KNOWN_DOCUMENT_IDS = frozenset(
    {
        "ORION-FIN-2025-001",
        "ORION-FIN-PDF-2025-001",
        "ORION-LEGAL-2026-001",
        "ORION-SHARED-2026-001",
        "ATLAS-FIN-2025-001",
        "ATLAS-FIN-PDF-2025-001",
        "ATLAS-LEGAL-2026-001",
        "ATLAS-SHARED-2026-001",
        "UNKNOWN-PRIVATE-999",
    }
)


class ManifestError(RuntimeError):
    pass


def _path(version: str) -> Path:
    if version != DEFAULT_SUITE_VERSION:
        raise ManifestError("Unknown evaluation suite version.")
    return Path(__file__).parent / "manifests" / f"v{version}.json"


@lru_cache(maxsize=1)
def load_manifest(version: str = DEFAULT_SUITE_VERSION) -> EvaluationManifest:
    path = _path(version)
    try:
        manifest = EvaluationManifest.model_validate_json(
            path.read_text(encoding="utf-8"), strict=True
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ManifestError("Evaluation manifest is invalid.") from exc
    ids = [case.id for case in manifest.cases]
    if len(ids) != 42:
        raise ManifestError("Evaluation manifest must contain exactly 42 cases.")
    if len(set(ids)) != len(ids):
        raise ManifestError("Evaluation case IDs must be unique.")
    counts = Counter(case.category for case in manifest.cases)
    if counts != Counter(EXPECTED_COUNTS):
        raise ManifestError("Evaluation category counts do not match the release suite contract.")
    referenced = {
        identifier
        for case in manifest.cases
        for identifier in (*case.expected.document_ids, *case.expected.forbidden_document_ids)
    }
    invalid = referenced - KNOWN_DOCUMENT_IDS
    if invalid:
        raise ManifestError("Evaluation manifest contains an unknown expected document ID.")
    return manifest


def manifest_hash(version: str = DEFAULT_SUITE_VERSION) -> str:
    manifest = load_manifest(version)
    canonical = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest_at_startup() -> None:
    load_manifest()
