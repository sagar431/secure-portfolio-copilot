from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.contracts import LLMProvider
from app.core.config import Settings
from app.core.errors import APIError
from app.embeddings.contracts import EmbeddingProvider
from app.evaluations.audit import record_evaluation_event
from app.evaluations.contracts import (
    EvaluationCaseStatus,
    EvaluationRunDetail,
    EvaluationRunList,
    EvaluationRunRequest,
    EvaluationRunStatus,
)
from app.evaluations.judge import create_optional_judge
from app.evaluations.manifest import load_manifest, manifest_hash
from app.evaluations.repository import (
    EvaluationAlreadyRunningError,
    create_run_guarded,
    finish_run,
    get_run,
    list_runs,
    mark_run_error,
    persist_case_result,
)
from app.evaluations.runner import EvaluationRunner
from app.evaluations.scorers import aggregate_metrics, has_authorization_leak, release_gates
from app.policies.models import AuthorizationContext


class EvaluationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        llm_provider: LLMProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.llm_provider = llm_provider

    async def execute(
        self,
        context: AuthorizationContext,
        request: EvaluationRunRequest,
        *,
        request_id: str,
    ) -> EvaluationRunDetail:
        manifest = load_manifest(request.suite_version)
        digest = manifest_hash(request.suite_version)
        try:
            run = await create_run_guarded(
                self.session,
                requested_by_user_id=context.identity.user_id,
                manifest_version=manifest.version,
                manifest_hash=digest,
                advisory_judge_enabled=request.enable_advisory_judge,
                max_judged_cases=request.max_judged_cases,
            )
        except EvaluationAlreadyRunningError:
            raise APIError(
                409, "evaluation_running", "An evaluation run is already active."
            ) from None
        record_evaluation_event(
            event="evaluation_run",
            outcome="started",
            reason_code="RUN_STARTED",
            request_id=request_id,
            run_id=run.id,
        )
        judge = None
        if request.enable_advisory_judge:
            try:
                judge = create_optional_judge(self.settings, maximum_calls=request.max_judged_cases)
            except RuntimeError:
                await mark_run_error(self.session, run, "JUDGE_UNAVAILABLE")
                raise APIError(
                    503, "judge_unavailable", "The advisory judge is unavailable."
                ) from None
        runner = EvaluationRunner(
            self.session,
            embedding_provider=self.embedding_provider,
            llm_provider=self.llm_provider,
            judge=judge,
        )
        results = []
        try:
            for case in manifest.cases:
                result = await runner.run_case(case, request_id=f"{request_id}:{case.id}")
                await persist_case_result(self.session, run=run, result=result)
                results.append(result)
            result_tuple = tuple(results)
            metrics = aggregate_metrics(manifest.cases, result_tuple)
            gates = release_gates(metrics)
            if has_authorization_leak(manifest.cases, result_tuple):
                status = EvaluationRunStatus.SECURITY_FAILED
                reason = "AUTHORIZATION_LEAK_CONFIRMED"
            elif any(item.status is EvaluationCaseStatus.ERROR for item in result_tuple):
                status = EvaluationRunStatus.ERROR
                reason = "CASE_EXECUTION_ERROR"
            elif all(item.passed for item in gates) and all(
                item.status is EvaluationCaseStatus.PASS for item in result_tuple
            ):
                status = EvaluationRunStatus.PASSED
                reason = "ALL_RELEASE_GATES_PASSED"
            else:
                status = EvaluationRunStatus.FAILED
                reason = "RELEASE_GATE_FAILED"
            await finish_run(
                self.session,
                run=run,
                status=status,
                safe_reason_code=reason,
                metrics=metrics.model_dump(mode="json"),
                gates=[gate.model_dump(mode="json") for gate in gates],
            )
        except Exception:
            await mark_run_error(self.session, run, "RUNNER_FAILED_SAFELY")
            record_evaluation_event(
                event="evaluation_run",
                outcome="error",
                reason_code="RUNNER_FAILED_SAFELY",
                request_id=request_id,
                run_id=run.id,
            )
            raise
        record_evaluation_event(
            event="evaluation_run",
            outcome=status.value.lower(),
            reason_code=reason,
            request_id=request_id,
            run_id=run.id,
        )
        detail = await get_run(self.session, run.id)
        if detail is None:
            raise RuntimeError("Persisted evaluation run was not found")
        return detail

    async def list(self) -> EvaluationRunList:
        return await list_runs(self.session)

    async def get(self, run_id: UUID) -> EvaluationRunDetail:
        detail = await get_run(self.session, run_id)
        if detail is None:
            raise APIError(404, "not_found", "Evaluation run was not found.")
        return detail
