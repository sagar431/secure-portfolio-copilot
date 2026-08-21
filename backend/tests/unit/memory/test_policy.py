import pytest

from app.memory.policy import MemoryPolicyError, derive_memory_acl
from app.models.memory import MemoryScope


@pytest.mark.parametrize(
    ("department", "visibility", "classification", "scope"),
    [
        ("finance", "DEPARTMENT_PRIVATE", "FINANCE_ONLY", MemoryScope.FINANCE),
        (
            "legal",
            "DEPARTMENT_PRIVATE",
            "LEGAL_ONLY_CONFIDENTIAL",
            MemoryScope.LEGAL,
        ),
        ("shared", "TENANT_SHARED", "TENANT_SHARED", MemoryScope.SHARED),
    ],
)
def test_source_memory_inherits_exact_acl(
    department: str, visibility: str, classification: str, scope: MemoryScope
) -> None:
    acl = derive_memory_acl(scope, ((department, visibility, classification),))
    assert acl.department == department
    assert acl.visibility == visibility
    assert acl.classification == classification
    assert acl.scope is scope


def test_private_memory_can_narrow_but_not_change_source_acl() -> None:
    acl = derive_memory_acl(
        MemoryScope.PRIVATE_USER,
        (("finance", "DEPARTMENT_PRIVATE", "FINANCE_ONLY"),),
    )
    assert acl.scope is MemoryScope.PRIVATE_USER
    assert acl.department == "finance"
    assert acl.classification == "FINANCE_ONLY"


def test_source_free_memory_must_be_private() -> None:
    acl = derive_memory_acl(MemoryScope.PRIVATE_USER, ())
    assert acl.department == "shared"
    assert acl.classification == "TENANT_SHARED"

    with pytest.raises(MemoryPolicyError):
        derive_memory_acl(MemoryScope.SHARED, ())


def test_finance_cannot_become_legal_or_shared() -> None:
    source = (("finance", "DEPARTMENT_PRIVATE", "FINANCE_ONLY"),)
    with pytest.raises(MemoryPolicyError):
        derive_memory_acl(MemoryScope.LEGAL, source)
    with pytest.raises(MemoryPolicyError):
        derive_memory_acl(MemoryScope.SHARED, source)


def test_mixed_source_acls_fail_closed() -> None:
    with pytest.raises(MemoryPolicyError):
        derive_memory_acl(
            MemoryScope.PRIVATE_USER,
            (
                ("finance", "DEPARTMENT_PRIVATE", "FINANCE_ONLY"),
                ("legal", "DEPARTMENT_PRIVATE", "LEGAL_ONLY_CONFIDENTIAL"),
            ),
        )
