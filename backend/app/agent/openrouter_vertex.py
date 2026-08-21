from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.models import (
    CompletedStep,
    DecisionResult,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    StructuredObservation,
)
from app.agent.prompts import (
    DECISION_SYSTEM_INSTRUCTION,
    PERCEPTION_SYSTEM_INSTRUCTION,
    initial_decision_prompt,
    mid_session_decision_prompt,
    step_result_perception_prompt,
    user_query_perception_prompt,
)
from app.mcp_gateway.contracts import PermittedToolDescriptor
from app.openrouter_vertex import (
    OpenRouterErrorCode,
    OpenRouterProviderError,
    OpenRouterVertexClient,
    json_contract_instruction,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class _OpenRouterVertexStructuredStage:
    def __init__(self, *, client: OpenRouterVertexClient, system_instruction: str) -> None:
        self.client = client
        self.system_instruction = system_instruction

    @property
    def model_name(self) -> str:
        return self.client.model_name

    async def generate(self, prompt: str, model: type[_ModelT]) -> _ModelT:
        parsed: _ModelT | None = None

        def validate_content(content: str) -> None:
            nonlocal parsed
            try:
                parsed = model.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None

        try:
            await self.client.complete(
                system_instruction=json_contract_instruction(
                    self.system_instruction, model.model_json_schema(mode="validation")
                ),
                prompt=prompt,
                content_validator=validate_content,
                max_attempts=2,
            )
            if parsed is None:
                raise AgentModelError(AgentModelErrorCode.INVALID_RESPONSE)
            return parsed
        except OpenRouterProviderError as exc:
            if exc.code == OpenRouterErrorCode.TIMEOUT:
                code = AgentModelErrorCode.TIMEOUT
            elif exc.code == OpenRouterErrorCode.TRANSIENT:
                code = AgentModelErrorCode.TRANSIENT
            elif exc.code in {
                OpenRouterErrorCode.INVALID_RESPONSE,
                OpenRouterErrorCode.INCOMPLETE_RESPONSE,
            }:
                code = AgentModelErrorCode.INVALID_RESPONSE
            else:
                code = AgentModelErrorCode.UNAVAILABLE
            raise AgentModelError(code) from None


class OpenRouterVertexPerceptionProvider:
    def __init__(self, *, client: OpenRouterVertexClient) -> None:
        self._stage = _OpenRouterVertexStructuredStage(
            client=client,
            system_instruction=PERCEPTION_SYSTEM_INSTRUCTION,
        )

    @property
    def model_name(self) -> str:
        return self._stage.model_name

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        return await self._stage.generate(user_query_perception_prompt(query), PerceptionSnapshot)

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
        result = await self._stage.generate(
            step_result_perception_prompt(
                query,
                previous,
                current_plan,
                completed_steps,
                observation,
                remaining_budgets,
            ),
            PerceptionSnapshot,
        )
        rationale = (result.rationale_summary or "").casefold().strip()
        if len(rationale) >= 16 and any(
            rationale in item.excerpt.casefold() or item.excerpt.casefold() in rationale
            for item in observation.evidence
        ):
            raise AgentModelError(AgentModelErrorCode.INVALID_RESPONSE)
        return result


class OpenRouterVertexDecisionProvider:
    def __init__(self, *, client: OpenRouterVertexClient) -> None:
        self._stage = _OpenRouterVertexStructuredStage(
            client=client,
            system_instruction=DECISION_SYSTEM_INSTRUCTION,
        )

    @property
    def model_name(self) -> str:
        return self._stage.model_name

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult:
        return await self._stage.generate(
            initial_decision_prompt(query, perception, permitted_tool_catalog), DecisionResult
        )

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult:
        return await self._stage.generate(
            mid_session_decision_prompt(
                query,
                perception,
                current_plan,
                completed_steps,
                permitted_tool_catalog,
            ),
            DecisionResult,
        )
