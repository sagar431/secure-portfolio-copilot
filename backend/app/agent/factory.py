from typing import NoReturn

from app.agent.contracts import (
    AgentModelError,
    AgentModelErrorCode,
    DecisionProvider,
    PerceptionProvider,
)
from app.agent.models import (
    CompletedStep,
    DecisionResult,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    StructuredObservation,
)
from app.agent.openrouter_vertex import (
    OpenRouterVertexDecisionProvider,
    OpenRouterVertexPerceptionProvider,
)
from app.agent.rule_based_fake import RuleBasedFakeAgentProvider
from app.core.config import Settings
from app.mcp_gateway.contracts import PermittedToolDescriptor
from app.model_routing import RouteReason
from app.openrouter_vertex import OpenRouterVertexClient


class DisabledAgentProvider:
    model_name = "disabled-agent-stages"

    @staticmethod
    def _disabled() -> NoReturn:
        raise AgentModelError(AgentModelErrorCode.UNAVAILABLE)

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        del query
        self._disabled()

    async def perceive_step_result(
        self,
        *,
        query: str,
        previous: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        observation: StructuredObservation,
        remaining_budgets: RemainingBudgets,
    ) -> PerceptionSnapshot:
        del query, previous, current_plan, completed_steps, observation, remaining_budgets
        self._disabled()

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult:
        del query, perception, permitted_tool_catalog
        self._disabled()

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult:
        del query, perception, current_plan, completed_steps, permitted_tool_catalog
        self._disabled()


def agent_route_reason(settings: Settings) -> str:
    if settings.llm_provider == "openrouter_vertex":
        return RouteReason.AGENTIC_REQUEST.value
    return "PROVIDER_SELECTED"


def create_agent_stage_providers(
    settings: Settings,
) -> tuple[PerceptionProvider, DecisionProvider]:
    if settings.llm_provider == "fake":
        fake_provider = RuleBasedFakeAgentProvider()
        return fake_provider, fake_provider
    if settings.llm_provider == "disabled" or settings.openrouter_api_key is None:
        disabled_provider = DisabledAgentProvider()
        return disabled_provider, disabled_provider
    client = OpenRouterVertexClient(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        provider=settings.openrouter_provider,
        model_name=settings.openrouter_heavy_model,
        timeout_seconds=settings.openrouter_heavy_timeout_seconds,
        max_output_tokens=settings.openrouter_heavy_max_output_tokens,
    )
    return (
        OpenRouterVertexPerceptionProvider(client=client),
        OpenRouterVertexDecisionProvider(client=client),
    )
