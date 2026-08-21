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
from app.runpod_kimi import KimiErrorCode, KimiProviderError, RunpodKimiClient

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_PERCEPTION_SCHEMA = PerceptionSnapshot.model_json_schema(mode="validation")
_DECISION_SCHEMA = DecisionResult.model_json_schema(mode="validation")


class _KimiStructuredStage:
    def __init__(self, *, client: RunpodKimiClient, system_instruction: str) -> None:
        self.client = client
        self.system_instruction = system_instruction

    @property
    def model_name(self) -> str:
        return self.client.model_name

    async def generate(
        self,
        prompt: str,
        schema_name: str,
        schema: dict[str, object],
        model: type[_ModelT],
    ) -> _ModelT:
        parsed: _ModelT | None = None

        def validate_content(content: str) -> None:
            nonlocal parsed
            try:
                parsed = model.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE) from None

        try:
            await self.client.complete(
                system_instruction=self.system_instruction,
                prompt=prompt,
                schema_name=schema_name,
                response_schema=schema,
                content_validator=validate_content,
            )
            if parsed is None:
                raise AgentModelError(AgentModelErrorCode.INVALID_RESPONSE)
            return parsed
        except KimiProviderError as exc:
            if exc.code == KimiErrorCode.TIMEOUT:
                code = AgentModelErrorCode.TIMEOUT
            elif exc.code == KimiErrorCode.TRANSIENT:
                code = AgentModelErrorCode.TRANSIENT
            elif exc.code in {
                KimiErrorCode.INVALID_RESPONSE,
                KimiErrorCode.INCOMPLETE_RESPONSE,
            }:
                code = AgentModelErrorCode.INVALID_RESPONSE
            else:
                code = AgentModelErrorCode.UNAVAILABLE
            raise AgentModelError(code) from None


class RunpodKimiPerceptionProvider:
    def __init__(self, *, client: RunpodKimiClient) -> None:
        self._stage = _KimiStructuredStage(
            client=client,
            system_instruction=PERCEPTION_SYSTEM_INSTRUCTION,
        )

    @property
    def model_name(self) -> str:
        return self._stage.model_name

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        return await self._stage.generate(
            user_query_perception_prompt(query),
            "perception_snapshot",
            _PERCEPTION_SCHEMA,
            PerceptionSnapshot,
        )

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
            "perception_snapshot",
            _PERCEPTION_SCHEMA,
            PerceptionSnapshot,
        )
        rationale = (result.rationale_summary or "").casefold().strip()
        if len(rationale) >= 16 and any(
            rationale in item.excerpt.casefold() or item.excerpt.casefold() in rationale
            for item in observation.evidence
        ):
            raise AgentModelError(AgentModelErrorCode.INVALID_RESPONSE)
        return result


class RunpodKimiDecisionProvider:
    def __init__(self, *, client: RunpodKimiClient) -> None:
        self._stage = _KimiStructuredStage(
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
            initial_decision_prompt(query, perception, permitted_tool_catalog),
            "decision_result",
            _DECISION_SCHEMA,
            DecisionResult,
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
            "decision_result",
            _DECISION_SCHEMA,
            DecisionResult,
        )
