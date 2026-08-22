from app.agent.approval_security import canonical_action_hash, classify_tool_risk
from app.agent.loop import _must_pause
from app.agent.models import Action, ActionType
from app.mcp_gateway.contracts import SearchAuthorizedDocumentsInput
from app.models.agent_runs import AgentControlMode, ApprovalRiskClass


def test_canonical_action_hash_binds_typed_arguments_without_exposing_them() -> None:
    first = Action(
        type=ActionType.TOOL_CALL,
        action_name="portfolio.search_authorized_documents",
        arguments=SearchAuthorizedDocumentsInput(query="Orion results", top_k=5),
        reason_code="SEARCH_AUTHORIZED_EVIDENCE",
    )
    same = first.model_copy(deep=True)
    changed = first.model_copy(
        update={"arguments": SearchAuthorizedDocumentsInput(query="Orion results", top_k=4)}
    )
    assert canonical_action_hash(first) == canonical_action_hash(same)
    assert canonical_action_hash(first) != canonical_action_hash(changed)
    assert len(canonical_action_hash(first)) == 64
    assert "Orion" not in canonical_action_hash(first)


def test_control_modes_and_default_risk_cannot_bypass_always_approval() -> None:
    safe_risk = classify_tool_risk("portfolio.search_authorized_documents")
    future_risk = classify_tool_risk("portfolio.future_write")
    assert safe_risk is ApprovalRiskClass.LOW_READ_ONLY
    assert future_risk is ApprovalRiskClass.ALWAYS_REQUIRE_APPROVAL
    assert _must_pause(AgentControlMode.GUIDED, safe_risk, "a", None)
    assert not _must_pause(AgentControlMode.BALANCED, safe_risk, "a", None)
    assert not _must_pause(AgentControlMode.AUTONOMOUS, safe_risk, "a", None)
    assert _must_pause(AgentControlMode.AUTONOMOUS, future_risk, "a", None)
    assert not _must_pause(AgentControlMode.AUTONOMOUS, future_risk, "a", "a")
