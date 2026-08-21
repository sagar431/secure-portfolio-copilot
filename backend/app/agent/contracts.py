from enum import StrEnum
from typing import Protocol

from app.agent.models import (
    Action,
    CompletedStep,
    DecisionResult,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    StructuredObservation,
)
from app.chat.contracts import GroundedGenerationRequest, LLMGeneration
from app.mcp_gateway.contracts import PermittedToolDescriptor
from app.policies.models import AuthorizationContext


class AgentModelErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    TRANSIENT = "TRANSIENT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"


class AgentModelError(RuntimeError):
    def __init__(self, code: AgentModelErrorCode) -> None:
        super().__init__("Agent model stage failed safely.")
        self.code = code


class PerceptionProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot: ...

    async def perceive_step_result(
        self,
        *,
        query: str,
        previous: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        observation: StructuredObservation,
        remaining_budgets: RemainingBudgets,
    ) -> PerceptionSnapshot: ...


class DecisionProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult: ...

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult: ...


class ApprovedToolGateway(Protocol):
    async def execute(
        self,
        *,
        action: Action,
        authorization_context: AuthorizationContext,
        permitted_tools: frozenset[str],
        request_id: str,
    ) -> StructuredObservation: ...


class GroundedFinalizer(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration: ...
