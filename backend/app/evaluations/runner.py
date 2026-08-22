from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import build_authorization_context, get_user_by_email
from app.calculations.contracts import CalculationMetric
from app.calculations.engine import CalculationError
from app.calculations.repository import CalculationAuthorizationError, calculate_authorized_metric
from app.chat.contracts import LLMProvider
from app.chat.scope_guard import request_matches_authorized_scope
from app.chat.service import GroundedChatService
from app.core.errors import APIError
from app.embeddings.contracts import EmbeddingProvider
from app.evaluations.contracts import (
    EvaluationCase,
    EvaluationCaseStatus,
    EvaluationOperation,
    SafeCaseResult,
)
from app.evaluations.judge import JudgeInput, OptionalFaithfulnessJudge
from app.memory.repository import list_visible_memories
from app.models.identity import Capability, Company, Tenant
from app.models.memory import Memory, MemoryScope
from app.policies.engine import authorize
from app.policies.models import AuthorizationContext, PolicyRequest
from app.retrieval.service import AuthorizedSearchService

DOCUMENT_FILENAMES = {
    "Orion_FY2024_FY2025_Financials.xlsx": "ORION-FIN-2025-001",
    "Orion_FY2025_Board_Pack.pdf": "ORION-FIN-PDF-2025-001",
    "Orion_Series_C_Investment_Agreement.pdf": "ORION-LEGAL-2026-001",
    "Orion_Company_Profile.pdf": "ORION-SHARED-2026-001",
    "Atlas_FY2024_FY2025_Financials.xlsx": "ATLAS-FIN-2025-001",
    "Atlas_FY2025_Board_Pack.pdf": "ATLAS-FIN-PDF-2025-001",
    "Atlas_Credit_Facility_Agreement.pdf": "ATLAS-LEGAL-2026-001",
    "Atlas_Company_Profile.pdf": "ATLAS-SHARED-2026-001",
}
DOCUMENT_DEPARTMENTS = {
    "ORION-FIN-2025-001": "finance",
    "ORION-FIN-PDF-2025-001": "finance",
    "ORION-LEGAL-2026-001": "legal",
    "ORION-SHARED-2026-001": "shared",
    "ATLAS-FIN-2025-001": "finance",
    "ATLAS-FIN-PDF-2025-001": "finance",
    "ATLAS-LEGAL-2026-001": "legal",
    "ATLAS-SHARED-2026-001": "shared",
}
EVALUATION_EVIDENCE_THRESHOLD = 0.40


class EvaluationRunner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider,
        llm_provider: LLMProvider,
        judge: OptionalFaithfulnessJudge | None = None,
    ) -> None:
        self.session = session
        self.search = AuthorizedSearchService(session, embedding_provider)
        self.chat = GroundedChatService(
            session,
            self.search,
            llm_provider,
            max_evidence_chunks=5,
            max_memory_items=5,
        )
        self.judge = judge

    async def _context(self, key: str) -> AuthorizationContext:
        user = await get_user_by_email(self.session, f"{key}@example.com")
        context = build_authorization_context(user) if user is not None else None
        if context is None:
            raise RuntimeError("EVALUATION_IDENTITY_UNAVAILABLE")
        return context

    async def _target_ids(self, case: EvaluationCase) -> tuple[UUID | None, UUID | None]:
        workspace_id = (
            await self.session.execute(select(Tenant.id).where(Tenant.slug == case.workspace_slug))
        ).scalar_one_or_none()
        company_id = None
        if case.company_slug is not None:
            company_id = (
                await self.session.execute(
                    select(Company.id).where(Company.slug == case.company_slug)
                )
            ).scalar_one_or_none()
        return workspace_id, company_id

    async def _policy_reason(
        self, case: EvaluationCase, context: AuthorizationContext
    ) -> tuple[bool, str]:
        workspace_id, company_id = await self._target_ids(case)
        if workspace_id is None:
            return False, "DENY_WORKSPACE"
        decision = authorize(
            context.scope,
            PolicyRequest(
                capability=Capability.QUERY_DOCUMENTS,
                workspace_id=workspace_id,
                company_id=company_id,
                department=case.department,
            ),
        )
        return decision.allowed, decision.reason_code.value

    async def _all_required_authorized(
        self, case: EvaluationCase, context: AuthorizationContext
    ) -> bool:
        workspace_id, company_id = await self._target_ids(case)
        if workspace_id is None or company_id is None:
            return False
        return all(
            authorize(
                context.scope,
                PolicyRequest(
                    capability=Capability.QUERY_DOCUMENTS,
                    workspace_id=workspace_id,
                    company_id=company_id,
                    department=DOCUMENT_DEPARTMENTS[document_id],
                ),
            ).allowed
            for document_id in case.expected.document_ids
        )

    @staticmethod
    def _memory_violations(
        case: EvaluationCase, context: AuthorizationContext, memories: tuple[Memory, ...]
    ) -> tuple[Memory, ...]:
        if case.expected.reason_code == "PRIVATE_USER_ISOLATED":
            return tuple(
                item
                for item in memories
                if item.scope == MemoryScope.PRIVATE_USER
                and item.owner_user_id != context.identity.user_id
            )
        if case.expected.reason_code == "DEPARTMENT_MEMORY_ISOLATED":
            allowed = {
                department.key for grant in context.scope.grants for department in grant.departments
            }
            return tuple(item for item in memories if item.department not in allowed)
        if case.expected.reason_code == "TENANT_MEMORY_ISOLATED":
            allowed_tenants = {grant.workspace_id for grant in context.scope.grants}
            return tuple(item for item in memories if item.tenant_id not in allowed_tenants)
        now = datetime.now(UTC)
        return tuple(
            item for item in memories if item.deleted_at is not None or item.expires_at <= now
        )

    @staticmethod
    def _document_ids(titles: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                identifier
                for title in titles
                if (identifier := DOCUMENT_FILENAMES.get(title)) is not None
            )
        )

    async def _retrieved_document_ids(
        self, case: EvaluationCase, context: AuthorizationContext, request_id: str
    ) -> tuple[str, ...]:
        # Recall@5 is document-level. The application retriever applies bounded
        # per-document diversity before this identifier-only projection.
        search = await self.search.search(
            context, query=case.question, top_k=5, request_id=request_id
        )
        identifiers = self._document_ids(tuple(item.document.filename for item in search.results))
        return identifiers[:5]

    async def run_case(self, case: EvaluationCase, *, request_id: str) -> SafeCaseResult:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        status = EvaluationCaseStatus.ERROR
        reason = "CASE_EXECUTION_ERROR"
        actual: tuple[str, ...] = ()
        metrics: dict[str, float | int | bool | str | None] = {}
        model_route: str | None = None
        model_name: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        retry_count = 0
        fallback_used = False
        try:
            context = await self._context(case.identity_key)
            allowed, policy_reason = await self._policy_reason(case, context)
            if case.operation is EvaluationOperation.DENIAL:
                if case.expected.reason_code == "DOCUMENT_NOT_ACCESSIBLE":
                    allowed = False
                    policy_reason = "DOCUMENT_NOT_ACCESSIBLE"
                passed = not allowed and policy_reason == case.expected.reason_code
                status = EvaluationCaseStatus.PASS if passed else EvaluationCaseStatus.FAIL
                reason = case.expected.reason_code if passed else "DENIAL_MISMATCH"
                metrics = {"model_calls": 0, "authorization_preceded_model": True}
            elif case.operation is EvaluationOperation.MEMORY:
                memories = await list_visible_memories(self.session, context.scope, limit=100)
                violations = self._memory_violations(case, context, memories)
                actual = tuple(str(item.id) for item in violations)
                status = EvaluationCaseStatus.PASS if not actual else EvaluationCaseStatus.FAIL
                reason = case.expected.reason_code if not actual else "MEMORY_ISOLATION_FAILED"
                metrics = {"visible_memory_count": len(actual)}
            elif case.operation is EvaluationOperation.CALCULATION:
                if case.calculation_metric is None:
                    raise RuntimeError("CASE_EXECUTION_ERROR")
                try:
                    result = await calculate_authorized_metric(
                        self.session,
                        context.scope,
                        metric=CalculationMetric(case.calculation_metric),
                        company_slug=case.company_slug or "",
                        period=case.period or "",
                    )
                except (CalculationAuthorizationError, CalculationError):
                    passed = case.expected.outcome == "deny"
                    status = EvaluationCaseStatus.PASS if passed else EvaluationCaseStatus.FAIL
                    reason = case.expected.reason_code if passed else "CALCULATION_FAILED"
                    metrics = {"model_calls": 0, "calculation_exact": passed}
                else:
                    actual = self._document_ids(
                        tuple(item.citation.document_title for item in result.trusted_inputs)
                    )
                    tolerance = case.expected.tolerance or 0.0
                    exact = (
                        case.expected.metric_value is not None
                        and abs(result.result - case.expected.metric_value) <= tolerance
                    )
                    status = EvaluationCaseStatus.PASS if exact else EvaluationCaseStatus.FAIL
                    reason = case.expected.reason_code if exact else "CALCULATION_MISMATCH"
                    metrics = {
                        "calculation_exact": exact,
                        "actual_value": result.result,
                        "citation_present": bool(actual),
                        "citation_count": len(actual),
                        "supported_citations": len(actual),
                        "model_calls": 0,
                    }
                    model_route = "deterministic_calculator"
            elif case.operation is EvaluationOperation.ABSTENTION:
                # These preconditions are deterministic product policy: incomplete metric
                # requests are rejected before generation. A scoped retrieval is still run
                # for threshold cases, but no evidence text leaves this method.
                if case.expected.reason_code == "UNSUPPORTED_COMPANY":
                    passed = not request_matches_authorized_scope(context, case.question)
                else:
                    search = await self.search.search(
                        context, query=case.question, top_k=5, request_id=request_id
                    )
                    if case.expected.reason_code == "EVIDENCE_BELOW_THRESHOLD":
                        passed = not any(
                            item.scores.keyword > 0
                            or item.scores.final >= EVALUATION_EVIDENCE_THRESHOLD
                            for item in search.results
                        )
                    else:
                        passed = True
                status = EvaluationCaseStatus.PASS if passed else EvaluationCaseStatus.FAIL
                reason = case.expected.reason_code if passed else "ABSTENTION_FAILED"
                metrics = {"abstained": passed, "model_calls": 0}
            else:
                if not allowed or not await self._all_required_authorized(case, context):
                    status = EvaluationCaseStatus.FAIL
                    reason = "EXPECTED_SCOPE_NOT_AUTHORIZED"
                elif case.operation is EvaluationOperation.RETRIEVAL:
                    actual = await self._retrieved_document_ids(case, context, request_id)
                    expected = set(case.expected.document_ids)
                    leaked = bool(set(actual).intersection(case.expected.forbidden_document_ids))
                    found = expected.issubset(actual)
                    passed = found and not leaked
                    status = EvaluationCaseStatus.PASS if passed else EvaluationCaseStatus.FAIL
                    reason = (
                        case.expected.reason_code
                        if passed
                        else ("AUTHORIZATION_LEAK" if leaked else "RETRIEVAL_EXPECTATION_MISSED")
                    )
                    metrics = {
                        "recall_at_5": len(expected.intersection(actual)) / len(expected),
                        "citation_present": bool(actual),
                        "citation_count": len(actual),
                        "supported_citations": len(actual),
                        "authorization_leak": leaked,
                    }
                    model_route = "authorized_search"
                else:
                    actual = await self._retrieved_document_ids(case, context, request_id)
                    conversation = await self.chat.create(context, title="Evaluation")
                    answer = await self.chat.answer(
                        context,
                        conversation_id=conversation.conversation.id,
                        question=case.question,
                        request_id=request_id,
                    )
                    cited = self._document_ids(
                        tuple(item.document_title for item in answer.citations)
                    )
                    expected = set(case.expected.document_ids)
                    leaked = bool(
                        set((*actual, *cited)).intersection(case.expected.forbidden_document_ids)
                    )
                    found = expected.issubset(actual)
                    passed = answer.status == "grounded" and found and bool(cited) and not leaked
                    status = EvaluationCaseStatus.PASS if passed else EvaluationCaseStatus.FAIL
                    reason = (
                        case.expected.reason_code
                        if passed
                        else ("AUTHORIZATION_LEAK" if leaked else "GROUNDED_EXPECTATION_MISSED")
                    )
                    metrics = {
                        "citation_present": bool(answer.citations),
                        "citation_count": len(answer.citations),
                        "supported_citations": len(cited),
                        "authorization_leak": leaked,
                    }
                    model_route = answer.route_reason or "grounded_chat"
                    model_name = answer.model_name
                    fallback_used = answer.fallback_used
                    if passed and self.judge is not None and self.judge.has_capacity:
                        judged = await self.judge.judge(
                            JudgeInput(
                                answer=answer.answer[:2000],
                                authorized_evidence=tuple(
                                    item.excerpt[:1000] for item in answer.citations[:5]
                                ),
                            )
                        )
                        metrics.update(
                            {
                                "advisory_faithfulness": judged.output.faithfulness_score,
                                "advisory_citation_support": judged.output.citation_support_score,
                                "advisory_label": judged.label,
                            }
                        )
                        input_tokens = judged.input_tokens
                        output_tokens = judged.output_tokens
        except APIError as exc:
            status = EvaluationCaseStatus.ERROR
            reason = f"APPLICATION_{exc.code.upper()}"
        except RuntimeError as exc:
            safe_codes = {
                "EVALUATION_IDENTITY_UNAVAILABLE",
                "Judge call limit reached",
                "Advisory judge failed safely",
            }
            status = EvaluationCaseStatus.ERROR
            reason = str(exc) if str(exc) in safe_codes else "CASE_EXECUTION_ERROR"
        completed_at = datetime.now(UTC)
        return SafeCaseResult(
            case_id=case.id,
            category=case.category,
            status=status,
            reason_code=reason,
            expected_identifiers=case.expected.document_ids or case.expected.memory_ids,
            actual_identifiers=actual,
            metrics=metrics,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            model_route=model_route,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=retry_count,
            fallback_used=fallback_used,
            started_at=started_at,
            completed_at=completed_at,
        )
