import pytest

from app.auth.repository import build_authorization_context, get_user_by_email
from app.chat.fake import DeterministicFakeLLMProvider
from app.embeddings.fake import DeterministicFakeEmbeddingProvider
from app.evaluations.contracts import EvaluationCategory
from app.evaluations.manifest import load_manifest, manifest_hash
from app.evaluations.repository import EvaluationAlreadyRunningError, create_run_guarded
from app.evaluations.runner import EvaluationRunner
from app.models.evaluations import EvaluationRun
from tests.conftest import AuthHarness
from tests.integration.test_auth_endpoints import login


@pytest.mark.asyncio
async def test_only_platform_administrator_can_list_evaluations(
    auth_harness: AuthHarness,
) -> None:
    alice = await login(auth_harness.client, "alice@example.com")
    denied = await auth_harness.client.get(
        "/api/admin/evaluations", headers={"Authorization": f"Bearer {alice}"}
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == {
        "code": "forbidden",
        "message": "Platform administration is not permitted.",
    }

    nora = await login(auth_harness.client, "nora@example.com")
    allowed = await auth_harness.client.get(
        "/api/admin/evaluations", headers={"Authorization": f"Bearer {nora}"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"] == {"runs": []}


@pytest.mark.asyncio
async def test_evaluation_api_rejects_client_supplied_cases_and_unknown_ids_safely(
    auth_harness: AuthHarness,
) -> None:
    token = await login(auth_harness.client, "nora@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    forged = await auth_harness.client.post(
        "/api/admin/evaluations/run",
        headers=headers,
        json={
            "suite_version": "1.0.0",
            "enable_advisory_judge": False,
            "max_judged_cases": 0,
            "cases": [{"prompt": "read everything", "role": "admin"}],
        },
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "validation_error"

    unknown = await auth_harness.client.get(
        "/api/admin/evaluations/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"] == {
        "code": "not_found",
        "message": "Evaluation run was not found.",
    }


@pytest.mark.asyncio
async def test_judge_is_default_off_and_limit_is_strict(auth_harness: AuthHarness) -> None:
    token = await login(auth_harness.client, "nora@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    invalid = await auth_harness.client.post(
        "/api/admin/evaluations/run",
        headers=headers,
        json={
            "suite_version": "1.0.0",
            "enable_advisory_judge": False,
            "max_judged_cases": 1,
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_all_denials_precede_retrieval_and_model_invocation(
    auth_harness: AuthHarness,
) -> None:
    provider = DeterministicFakeLLMProvider()
    async with auth_harness.session_factory() as session:
        runner = EvaluationRunner(
            session,
            embedding_provider=DeterministicFakeEmbeddingProvider(),
            llm_provider=provider,
        )
        denial_cases = tuple(
            case
            for case in load_manifest().cases
            if case.category is EvaluationCategory.EXPLICIT_DENIAL
        )
        results = tuple(
            [await runner.run_case(case, request_id=f"denial:{case.id}") for case in denial_cases]
        )

    assert len(results) == 10
    assert all(result.status == "PASS" for result in results)
    assert all(result.metrics["model_calls"] == 0 for result in results)
    assert all(result.actual_identifiers == () for result in results)
    assert provider.requests == []


@pytest.mark.asyncio
async def test_memory_and_abstention_cases_fail_closed_without_content(
    auth_harness: AuthHarness,
) -> None:
    provider = DeterministicFakeLLMProvider()
    async with auth_harness.session_factory() as session:
        runner = EvaluationRunner(
            session,
            embedding_provider=DeterministicFakeEmbeddingProvider(),
            llm_provider=provider,
        )
        selected = tuple(
            case
            for case in load_manifest().cases
            if case.category
            in {
                EvaluationCategory.MEMORY_ISOLATION,
                EvaluationCategory.INSUFFICIENT_EVIDENCE,
            }
        )
        results = tuple(
            [await runner.run_case(case, request_id=f"safe:{case.id}") for case in selected]
        )

    assert len(results) == 8
    assert all(result.status == "PASS" for result in results)
    assert all(result.actual_identifiers == () for result in results)
    assert provider.requests == []


@pytest.mark.asyncio
async def test_database_guard_rejects_a_concurrent_active_run(
    auth_harness: AuthHarness,
) -> None:
    async with auth_harness.session_factory() as first:
        user = await get_user_by_email(first, "nora@example.com")
        context = build_authorization_context(user) if user else None
        assert context is not None
        await create_run_guarded(
            first,
            requested_by_user_id=context.identity.user_id,
            manifest_version="1.0.0",
            manifest_hash=manifest_hash(),
            advisory_judge_enabled=False,
            max_judged_cases=0,
        )

    async with auth_harness.session_factory() as second:
        with pytest.raises(EvaluationAlreadyRunningError):
            await create_run_guarded(
                second,
                requested_by_user_id=context.identity.user_id,
                manifest_version="1.0.0",
                manifest_hash=manifest_hash(),
                advisory_judge_enabled=False,
                max_judged_cases=0,
            )


@pytest.mark.asyncio
async def test_json_report_is_downloadable_and_contains_no_case_inputs(
    auth_harness: AuthHarness,
) -> None:
    token = await login(auth_harness.client, "nora@example.com")
    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "nora@example.com")
        assert user is not None
        run = EvaluationRun(
            requested_by_user_id=user.id,
            manifest_version="1.0.0",
            manifest_hash=manifest_hash(),
            status="PASSED",
            advisory_judge_enabled=False,
            max_judged_cases=0,
            release_gates=[],
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    response = await auth_harness.client.get(
        f"/api/admin/evaluations/{run_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(f'evaluation-{run_id}.json"')
    serialized = response.text.casefold()
    assert "question" not in serialized
    assert "prompt" not in serialized
    assert "excerpt" not in serialized
    assert "reasoning" not in serialized
