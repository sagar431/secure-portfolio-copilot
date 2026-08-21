from typing import NoReturn

from app.agent.contracts import (
    AgentModelError,
    AgentModelErrorCode,
    DecisionProvider,
    PerceptionProvider,
)
from app.agent.gemini import GeminiDecisionProvider, GeminiPerceptionProvider
from app.agent.models import (
    CompletedStep,
    DecisionResult,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    StructuredObservation,
)
from app.agent.rule_based_fake import RuleBasedFakeAgentProvider
from app.agent.runpod import RunpodKimiDecisionProvider, RunpodKimiPerceptionProvider
from app.core.config import Settings
from app.mcp_gateway.contracts import PermittedToolDescriptor
from app.runpod_kimi import RunpodKimiClient


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


def create_agent_stage_providers(
    settings: Settings,
) -> tuple[PerceptionProvider, DecisionProvider]:
    if settings.llm_provider == "fake":
        fake_provider = RuleBasedFakeAgentProvider()
        return fake_provider, fake_provider
    if settings.llm_provider == "disabled":
        disabled_provider = DisabledAgentProvider()
        return disabled_provider, disabled_provider
    if settings.llm_provider == "runpod":
        if settings.runpod_api_key is None:
            disabled_provider = DisabledAgentProvider()
            return disabled_provider, disabled_provider
        client = RunpodKimiClient(
            api_key=settings.runpod_api_key.get_secret_value(),
            base_url=settings.runpod_base_url,
            model_name=settings.runpod_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        )
        return RunpodKimiPerceptionProvider(client=client), RunpodKimiDecisionProvider(
            client=client
        )
    if settings.gemini_api_key is None:
        disabled_provider = DisabledAgentProvider()
        return disabled_provider, disabled_provider
    api_key = settings.gemini_api_key.get_secret_value()
    return (
        GeminiPerceptionProvider(
            api_key=api_key,
            model_name=settings.llm_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        ),
        GeminiDecisionProvider(
            api_key=api_key,
            model_name=settings.llm_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        ),
    )
