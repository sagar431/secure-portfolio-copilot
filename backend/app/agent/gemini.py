import asyncio
import json
from typing import TypeVar

from google import genai
from google.genai import errors, types
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
from app.agent.provider_schema import provider_schema
from app.mcp_gateway.contracts import PermittedToolDescriptor

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_PERCEPTION_SCHEMA = provider_schema(PerceptionSnapshot)
_DECISION_SCHEMA = provider_schema(DecisionResult)


class _GeminiStructuredStage:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
        system_instruction: str,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.system_instruction = system_instruction

    async def _once(self, prompt: str, schema: dict[str, object], model: type[_ModelT]) -> _ModelT:
        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=int(self.timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=0,
                        candidate_count=1,
                        max_output_tokens=self.max_output_tokens,
                        response_mime_type="application/json",
                        response_schema=schema,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.MEDIUM, include_thoughts=False
                        ),
                    ),
                )
        finally:
            await client.aio.aclose()
        return model.model_validate_json(json.dumps(response.parsed), strict=True)

    async def generate(
        self, prompt: str, schema: dict[str, object], model: type[_ModelT]
    ) -> _ModelT:
        for attempt in range(2):
            try:
                return await self._once(prompt, schema, model)
            except TimeoutError:
                error = AgentModelError(AgentModelErrorCode.TIMEOUT)
                transient = True
            except errors.APIError as exc:
                transient = exc.code in {408, 429} or exc.code >= 500
                error = AgentModelError(
                    AgentModelErrorCode.TRANSIENT if transient else AgentModelErrorCode.UNAVAILABLE
                )
            except (TypeError, ValueError, ValidationError):
                raise AgentModelError(AgentModelErrorCode.INVALID_RESPONSE) from None
            except Exception:
                raise AgentModelError(AgentModelErrorCode.UNAVAILABLE) from None
            if not transient or attempt == 1:
                raise error from None
        raise AgentModelError(AgentModelErrorCode.UNAVAILABLE)


class GeminiPerceptionProvider:
    def __init__(
        self, *, api_key: str, model_name: str, timeout_seconds: float, max_output_tokens: int
    ) -> None:
        self._stage = _GeminiStructuredStage(
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            system_instruction=PERCEPTION_SYSTEM_INSTRUCTION,
        )

    @property
    def model_name(self) -> str:
        return self._stage.model_name

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        return await self._stage.generate(
            user_query_perception_prompt(query),
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


class GeminiDecisionProvider:
    def __init__(
        self, *, api_key: str, model_name: str, timeout_seconds: float, max_output_tokens: int
    ) -> None:
        self._stage = _GeminiStructuredStage(
            api_key=api_key,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
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
            _DECISION_SCHEMA,
            DecisionResult,
        )
