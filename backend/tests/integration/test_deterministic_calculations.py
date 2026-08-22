from typing import Any

import pytest
from sqlalchemy import select

from app.auth.repository import build_authorization_context, get_user_by_email
from app.mcp_gateway.adapters import CalculateEbitdaMarginAdapter
from app.mcp_gateway.contracts import CalculateFinancialMetricInput, CalculationPayload
from app.mcp_gateway.errors import ToolAuthorizationError
from app.models.documents import ParsedCell, ParsedRow, ParsedSheet
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import (
    XLSX_MEDIA_TYPE,
    _login,
    _metadata,
    _upload_and_approve,
)
from tests.integration.test_grounded_chat import _create_conversation


async def _run(harness: AuthHarness, token: str, conversation_id: str, question: str) -> Any:
    return await harness.client.post(
        f"/api/conversations/{conversation_id}/agent-runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": question},
    )


async def _prepare_orion_workbook(harness: AuthHarness) -> None:
    nora = await _login(harness.client, "nora@example.com")
    await _upload_and_approve(
        harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2024_FY2025_Financials.xlsx",
        media_type=XLSX_MEDIA_TYPE,
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="SPREADSHEET",
            reporting_period="FY2024-FY2025",
        ),
        idempotency_key="calculation-orion-workbook-1",
    )


@pytest.mark.asyncio
async def test_three_calculator_tools_return_host_computed_results_and_citations(
    auth_harness: AuthHarness,
) -> None:
    await _prepare_orion_workbook(auth_harness)
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Deterministic calculations")
    cases = (
        ("Calculate Orion EBITDA margin for FY2025", "ebitda_margin", 10.0, 3),
        ("Calculate Orion revenue growth for FY2025", "revenue_growth", 25.0, 2),
        ("Calculate Orion net profit margin for FY2025", "net_profit_margin", 3.0, 6),
    )

    for question, metric, expected, input_count in cases:
        response = await _run(auth_harness, alice, str(conversation["id"]), question)
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        assert payload["terminal_status"] == "completed"
        assert payload["stopping_reason"] == "completed"
        assert len(payload["calculations"]) == 1
        calculation = payload["calculations"][0]
        assert calculation["metric"] == metric
        assert calculation["company_slug"] == "orion-main"
        assert calculation["period"] == "FY2025"
        assert calculation["result"] == expected
        assert calculation["unit"] == "percent"
        assert calculation["formula"]
        assert len(calculation["trusted_inputs"]) == input_count
        assert all(item["unit"] == "INR crore" for item in calculation["trusted_inputs"])
        assert all(item["cell_start"] == item["cell_end"] for item in payload["citations"])
        assert calculation["citation_ids"] == [
            item["citation_id"] for item in calculation["trusted_inputs"]
        ]
        assert {item["citation_id"] for item in payload["citations"]} == set(
            calculation["citation_ids"]
        )
        assert payload["claims"][0]["citation_ids"] == calculation["citation_ids"]
        assert any(
            item["reason_code"] == "DETERMINISTIC_CALCULATION_VALIDATED"
            for item in payload["trace"]
        )
        assert not any(item["reason_code"] == "FINALIZATION_STARTED" for item in payload["trace"])


@pytest.mark.asyncio
async def test_calculator_resolves_unique_authorized_workspace_alias_to_canonical_company(
    auth_harness: AuthHarness,
) -> None:
    await _prepare_orion_workbook(auth_harness)

    async with auth_harness.session_factory() as session:
        alice = await get_user_by_email(session, "alice@example.com")
        assert alice is not None
        context = build_authorization_context(alice)
        assert context is not None

        payload = await CalculateEbitdaMarginAdapter(session).invoke(
            arguments=CalculateFinancialMetricInput(
                company_slug="orion",
                reporting_period="FY2025",
            ),
            authorization_scope=context.scope,
            request_id="calculation-authorized-alias",
        )
        with pytest.raises(ToolAuthorizationError):
            await CalculateEbitdaMarginAdapter(session).invoke(
                arguments=CalculateFinancialMetricInput(
                    company_slug="atlas",
                    reporting_period="FY2025",
                ),
                authorization_scope=context.scope,
                request_id="calculation-unauthorized-alias",
            )

    assert isinstance(payload, CalculationPayload)
    assert len(payload.calculations) == 1
    calculation = payload.calculations[0]
    assert calculation.company_slug == "orion-main"
    assert calculation.result == 10.0


@pytest.mark.asyncio
async def test_missing_invalid_and_unauthorized_calculation_inputs_fail_closed(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    alice_conversation = await _create_conversation(auth_harness, alice, "Missing calculator")
    missing = await _run(
        auth_harness,
        alice,
        str(alice_conversation["id"]),
        "Calculate Orion EBITDA margin for FY2025",
    )
    assert missing.status_code == 200
    assert missing.json()["data"]["terminal_status"] == "failed"
    assert missing.json()["data"]["calculations"] == []
    assert any(
        item["reason_code"] == "CALCULATION_INPUTS_MISSING"
        for item in missing.json()["data"]["trace"]
    )

    await _prepare_orion_workbook(auth_harness)
    leo_conversation = await _create_conversation(auth_harness, leo, "Denied calculator")
    denied = await _run(
        auth_harness,
        leo,
        str(leo_conversation["id"]),
        "Calculate Orion EBITDA margin for FY2025",
    )
    assert denied.status_code == 200
    assert denied.json()["data"]["terminal_status"] == "refused"
    assert denied.json()["data"]["calculations"] == []
    assert any(
        item["reason_code"] == "AUTHORIZATION_DENIED" for item in denied.json()["data"]["trace"]
    )

    async with auth_harness.session_factory() as session:
        revenue = (
            (
                await session.execute(
                    select(ParsedCell)
                    .join(ParsedRow, ParsedRow.id == ParsedCell.row_id)
                    .join(ParsedSheet, ParsedSheet.id == ParsedRow.sheet_id)
                    .where(ParsedSheet.name == "P&L", ParsedCell.coordinate == "C4")
                )
            )
            .scalars()
            .one()
        )
        revenue.value_text = "0"
        await session.commit()
    division_by_zero = await _run(
        auth_harness,
        alice,
        str(alice_conversation["id"]),
        "Calculate Orion EBITDA margin for FY2025",
    )
    assert division_by_zero.status_code == 200
    assert division_by_zero.json()["data"]["terminal_status"] == "failed"
    assert division_by_zero.json()["data"]["calculations"] == []
    assert any(
        item["reason_code"] == "CALCULATION_DIVISION_BY_ZERO"
        for item in division_by_zero.json()["data"]["trace"]
    ), [item["reason_code"] for item in division_by_zero.json()["data"]["trace"]]

    async with auth_harness.session_factory() as session:
        revenue = (
            (
                await session.execute(
                    select(ParsedCell)
                    .join(ParsedRow, ParsedRow.id == ParsedCell.row_id)
                    .join(ParsedSheet, ParsedSheet.id == ParsedRow.sheet_id)
                    .where(ParsedSheet.name == "P&L", ParsedCell.coordinate == "C4")
                )
            )
            .scalars()
            .one()
        )
        revenue.value_text = "model-estimated-value"
        await session.commit()
    malformed = await _run(
        auth_harness,
        alice,
        str(alice_conversation["id"]),
        "Calculate Orion EBITDA margin for FY2025",
    )
    assert malformed.status_code == 200
    assert malformed.json()["data"]["terminal_status"] == "failed"
    assert malformed.json()["data"]["calculations"] == []
    assert any(
        item["reason_code"] == "CALCULATION_INPUTS_INVALID"
        for item in malformed.json()["data"]["trace"]
    ), [item["reason_code"] for item in malformed.json()["data"]["trace"]]
