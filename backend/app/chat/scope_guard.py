import re
from uuid import UUID

from app.core.errors import APIError
from app.models.identity import Capability
from app.policies.models import AuthorizationContext

_TARGET_BEFORE_DOMAIN = re.compile(
    r"\b([a-z0-9_-]+)(?:'s)?\s+"
    r"(?:finance|financial|legal|company|portfolio|documents?|data)\b",
    re.IGNORECASE,
)
_TARGET_BEFORE_METRIC = re.compile(
    r"(?:^|\bwhat\s+(?:was|is)|\bwhy\s+did|\bshow\s+me|\bsummarize)\s+"
    r"([a-z0-9_-]+)(?:'s)?\s+"
    r"(?:revenue|ebitda|margin|agreement|contract|board)\b",
    re.IGNORECASE,
)
_TARGET_AFTER_PREPOSITION = re.compile(r"\b(?:for|from|about|at)\s+([a-z0-9_-]+)\b", re.IGNORECASE)
_TARGET_STOP_WORDS = {
    "authorized",
    "company",
    "document",
    "documents",
    "ebitda",
    "evidence",
    "financial",
    "gross",
    "is",
    "legal",
    "margin",
    "me",
    "my",
    "net",
    "now",
    "operating",
    "of",
    "our",
    "portfolio",
    "prefer",
    "remember",
    "revenue",
    "the",
    "this",
    "was",
    "were",
}


def resolve_home_tenant_id(context: AuthorizationContext) -> UUID:
    tenant_ids = {grant.home_tenant_id for grant in context.scope.grants}
    if len(tenant_ids) != 1:
        raise APIError(403, "forbidden", "Conversation access is not permitted.")
    return next(iter(tenant_ids))


def request_matches_authorized_scope(context: AuthorizationContext, question: str) -> bool:
    """Conservative preflight only; database authorization remains authoritative."""
    query_tokens = set(re.findall(r"[a-z0-9_-]+", question.casefold()))
    authorized_departments = {
        department.key.casefold()
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
        for department in grant.departments
    }
    requested_departments = query_tokens.intersection({"finance", "legal", "shared"})
    if not requested_departments.issubset(authorized_departments):
        return False
    authorized_targets = {
        token
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
        for value in (grant.workspace_slug, *grant.company_slugs)
        for token in (value.casefold(), value.casefold().split("-", 1)[0])
    }
    target_hints = {
        match.group(1).casefold()
        for pattern in (
            _TARGET_BEFORE_DOMAIN,
            _TARGET_BEFORE_METRIC,
            _TARGET_AFTER_PREPOSITION,
        )
        for match in pattern.finditer(question)
        if match.group(1).casefold() not in _TARGET_STOP_WORDS
        and not re.fullmatch(r"fy\d{4}", match.group(1), re.IGNORECASE)
    }
    return not target_hints or target_hints.issubset(authorized_targets)
