from typing import NoReturn

from app.agent.contracts import (
    AgentModelError,
    AgentModelErrorCode,
    DecisionProvider,
    PerceptionProvider,
)
from app.agent.gemini import GeminiDecisionProvider, GeminiPerceptionProvider
from app.agent.models import DecisionResult, PerceptionSnapshot, Plan, Step, StructuredObservation
from app.agent.rule_based_fake import RuleBasedFakeAgentProvider
from app.core.config import Settings


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
        observation: StructuredObservation,
    ) -> PerceptionSnapshot:
        del query, previous, observation
        self._disabled()

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        del query, perception, permitted_tools
        self._disabled()

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[Step, ...],
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        del query, perception, current_plan, completed_steps, permitted_tools
        self._disabled()


def create_agent_stage_providers(
    settings: Settings,
) -> tuple[PerceptionProvider, DecisionProvider]:
    if settings.llm_provider == "fake":
        fake_provider = RuleBasedFakeAgentProvider()
        return fake_provider, fake_provider
    if settings.llm_provider == "disabled" or settings.gemini_api_key is None:
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
