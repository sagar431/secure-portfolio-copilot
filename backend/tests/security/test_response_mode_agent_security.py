from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.agent.service import AgentRunService
from app.core.errors import APIError
from app.model_routing import ResponseMode
from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationContext,
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)


def _context() -> AuthorizationContext:
    identity = TrustedIdentity(user_id=uuid4(), email="agent@example.com", display_name="Agent")
    grant = AuthorizationGrant(
        membership_id=uuid4(),
        home_tenant_id=uuid4(),
        home_tenant_slug="orion",
        home_tenant_name="Orion",
        workspace_id=uuid4(),
        workspace_slug="orion",
        workspace_name="Orion",
        role="analyst",
        primary_department="finance",
        company_ids=(uuid4(),),
        company_slugs=("orion-main",),
        departments=(DepartmentAccess(key="finance", source=GrantSource.PRIMARY_DEPARTMENT),),
        capabilities=(Capability.QUERY_DOCUMENTS,),
    )
    return AuthorizationContext(
        identity=identity,
        scope=AuthorizationScope(identity=identity, grants=(grant,)),
    )


class _Session:
    async def commit(self) -> None:
        raise AssertionError("Fast rejection must not commit messages or traces")


class _Loop:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **_: object) -> object:
        self.calls += 1
        raise AssertionError("Fast agent rejection reached Perception or Decision")


class _Gateway:
    def __init__(self) -> None:
        self.calls = 0

    def permitted_catalog(self, *_: object) -> tuple[object, ...]:
        self.calls += 1
        raise AssertionError("Fast agent rejection reached MCP or tool selection")


@pytest.mark.asyncio
async def test_fast_agent_rejects_before_messages_perception_decision_mcp_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=context.scope.grants[0].home_tenant_id,
        user_id=context.identity.user_id,
    )
    message_calls = 0

    async def conversation_lookup(*_: object, **__: object) -> object:
        return conversation

    async def message_write(*_: object, **__: object) -> object:
        nonlocal message_calls
        message_calls += 1
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.agent.service.get_owned_conversation", conversation_lookup)
    monkeypatch.setattr("app.agent.service.add_message", message_write)
    loop = _Loop()
    gateway = _Gateway()
    service = AgentRunService(
        cast(Any, _Session()),
        cast(Any, loop),
        cast(Any, gateway),
        model_name="google/gemini-3.7-flash",
        route_reason_code="AGENTIC_REQUEST",
    )

    with pytest.raises(APIError) as captured:
        await service.run(
            context,
            conversation_id=conversation.id,
            question="calculate orion revenue growth",
            response_mode=ResponseMode.FAST,
            request_id="fast-agent-upgrade",
        )

    assert captured.value.status_code == 409
    assert captured.value.code == "deep_mode_required"
    assert message_calls == 0
    assert loop.calls == 0
    assert gateway.calls == 0
