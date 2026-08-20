from collections import deque

from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.models import (
    Action,
    DecisionResult,
    PerceptionSnapshot,
    Plan,
    Step,
    StructuredObservation,
)
from app.policies.models import AuthorizationContext


class DeterministicFakePerceptionProvider:
    model_name = "fake-agent-perception-v1"

    def __init__(
        self,
        snapshots: tuple[PerceptionSnapshot | AgentModelError, ...],
    ) -> None:
        self._snapshots = deque(snapshots)
        self.user_query_calls = 0
        self.step_result_calls = 0

    def _next(self) -> PerceptionSnapshot:
        if not self._snapshots:
            raise AgentModelError(code=AgentModelErrorCode.UNAVAILABLE)
        result = self._snapshots.popleft()
        if isinstance(result, AgentModelError):
            raise result
        return result

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        self.user_query_calls += 1
        return self._next()

    async def perceive_step_result(
        self,
        *,
        query: str,
        previous: PerceptionSnapshot,
        observation: StructuredObservation,
    ) -> PerceptionSnapshot:
        self.step_result_calls += 1
        return self._next()


class DeterministicFakeDecisionProvider:
    model_name = "fake-agent-decision-v1"

    def __init__(self, decisions: tuple[DecisionResult | AgentModelError, ...]) -> None:
        self._decisions = deque(decisions)
        self.initial_calls = 0
        self.mid_session_calls = 0

    def _next(self) -> DecisionResult:
        if not self._decisions:
            raise AgentModelError(code=AgentModelErrorCode.UNAVAILABLE)
        result = self._decisions.popleft()
        if isinstance(result, AgentModelError):
            raise result
        return result

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        self.initial_calls += 1
        return self._next()

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[Step, ...],
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        self.mid_session_calls += 1
        return self._next()


class DeterministicFakeGateway:
    """Loop fake only; production adapters must revalidate database-backed scope."""

    def __init__(self, observations: tuple[StructuredObservation, ...]) -> None:
        self._observations = deque(observations)
        self.calls: list[tuple[str, AuthorizationContext, frozenset[str], str]] = []

    async def execute(
        self,
        *,
        action: Action,
        authorization_context: AuthorizationContext,
        permitted_tools: frozenset[str],
        request_id: str,
    ) -> StructuredObservation:
        self.calls.append(
            (action.action_name or "", authorization_context, permitted_tools, request_id)
        )
        if not self._observations:
            raise RuntimeError("Fake gateway response missing")
        return self._observations.popleft()
