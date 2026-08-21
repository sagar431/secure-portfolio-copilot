from dataclasses import dataclass

from app.models.documents import DocumentClassification, DocumentVisibility
from app.models.memory import MemoryScope


@dataclass(frozen=True, slots=True)
class EffectiveMemoryACL:
    scope: MemoryScope
    department: str
    visibility: str
    classification: str


class MemoryPolicyError(ValueError):
    pass


_ACL_BY_DEPARTMENT = {
    "finance": (
        DocumentVisibility.DEPARTMENT_PRIVATE.value,
        DocumentClassification.FINANCE_ONLY.value,
    ),
    "legal": (
        DocumentVisibility.DEPARTMENT_PRIVATE.value,
        DocumentClassification.LEGAL_ONLY_CONFIDENTIAL.value,
    ),
    "shared": (
        DocumentVisibility.TENANT_SHARED.value,
        DocumentClassification.TENANT_SHARED.value,
    ),
}
_SCOPE_BY_DEPARTMENT = {
    "finance": MemoryScope.FINANCE,
    "legal": MemoryScope.LEGAL,
    "shared": MemoryScope.SHARED,
}


def derive_memory_acl(
    requested_scope: MemoryScope,
    source_acls: tuple[tuple[str, str, str], ...],
) -> EffectiveMemoryACL:
    """Inherit exact source restrictions; only private storage may narrow visibility."""

    if not source_acls:
        if requested_scope is not MemoryScope.PRIVATE_USER:
            raise MemoryPolicyError("Source-free memory must be private.")
        return EffectiveMemoryACL(
            requested_scope,
            "shared",
            DocumentVisibility.TENANT_SHARED.value,
            DocumentClassification.TENANT_SHARED.value,
        )
    unique = set(source_acls)
    if len(unique) != 1:
        raise MemoryPolicyError("Mixed source restrictions cannot be represented safely.")
    department, visibility, classification = unique.pop()
    if _ACL_BY_DEPARTMENT.get(department) != (visibility, classification):
        raise MemoryPolicyError("Source restriction is invalid.")
    inherited_scope = _SCOPE_BY_DEPARTMENT[department]
    if requested_scope not in {MemoryScope.PRIVATE_USER, inherited_scope}:
        raise MemoryPolicyError("Requested scope would change source restrictions.")
    return EffectiveMemoryACL(requested_scope, department, visibility, classification)
