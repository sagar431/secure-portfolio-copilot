"""SQLAlchemy domain models registered with Alembic metadata."""

from app.models.chat import ChatRequestTrace, Conversation, Message
from app.models.documents import (
    Document,
    DocumentAuditEvent,
    DocumentChunk,
    DocumentVersion,
    IngestionJob,
    ParsedCell,
    ParsedPage,
    ParsedRow,
    ParsedSheet,
)
from app.models.identity import (
    Company,
    CompanyGrant,
    Department,
    DepartmentGrant,
    Membership,
    Role,
    Tenant,
    User,
    WorkspaceGrant,
)

__all__ = [
    "Company",
    "CompanyGrant",
    "ChatRequestTrace",
    "Conversation",
    "Department",
    "DepartmentGrant",
    "Document",
    "DocumentAuditEvent",
    "DocumentChunk",
    "DocumentVersion",
    "IngestionJob",
    "Membership",
    "Message",
    "ParsedCell",
    "ParsedPage",
    "ParsedRow",
    "ParsedSheet",
    "Role",
    "Tenant",
    "User",
    "WorkspaceGrant",
]
