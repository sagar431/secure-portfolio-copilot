"""SQLAlchemy domain models registered with Alembic metadata."""

from app.models.agent_runs import AgentObservationRecord, AgentPlanVersion, AgentRun, AgentStep
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
from app.models.evaluations import EvaluationCaseResult, EvaluationRun
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
from app.models.memory import Memory, MemorySource

__all__ = [
    "AgentObservationRecord",
    "AgentPlanVersion",
    "AgentRun",
    "AgentStep",
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
    "EvaluationCaseResult",
    "EvaluationRun",
    "IngestionJob",
    "Membership",
    "Message",
    "Memory",
    "MemorySource",
    "ParsedCell",
    "ParsedPage",
    "ParsedRow",
    "ParsedSheet",
    "Role",
    "Tenant",
    "User",
    "WorkspaceGrant",
]
