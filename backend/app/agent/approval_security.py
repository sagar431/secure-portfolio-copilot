from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.agent.models import Action
from app.models.agent_runs import ApprovalRiskClass
from app.policies.models import AuthorizationScope

APPROVAL_LIFETIME = timedelta(minutes=5)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical_action_hash(action: Action) -> str:
    payload = {
        "action_name": action.action_name,
        "action_type": action.type.value,
        "arguments": action.arguments.model_dump(mode="json"),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def authorization_scope_fingerprint(scope: AuthorizationScope) -> str:
    # This digest binds the complete current scope without persisting or exposing that scope.
    return hashlib.sha256(_canonical_json(scope.model_dump(mode="json"))).hexdigest()


def classify_tool_risk(tool_name: str) -> ApprovalRiskClass:
    if tool_name in {
        "portfolio.search_authorized_documents",
        "portfolio.get_document_excerpt",
        "portfolio.calculate_ebitda_margin",
        "portfolio.calculate_revenue_growth",
        "portfolio.calculate_net_profit_margin",
    }:
        return ApprovalRiskClass.LOW_READ_ONLY
    # Future tools are denied by the allowlist; this class also prevents autonomy bypass.
    return ApprovalRiskClass.ALWAYS_REQUIRE_APPROVAL
