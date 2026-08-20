from app.agent.models import (
    Action,
    ActionType,
    DecisionResult,
    EvidenceStatus,
    GoalStatus,
    PerceptionMode,
    PerceptionSnapshot,
    Plan,
    Step,
    StructuredObservation,
)

SEARCH_TOOL = "portfolio.search_authorized_documents"


class RuleBasedFakeAgentProvider:
    """Deterministic test-only Perception and Decision provider."""

    model_name = "fake-agent-stages-v1"

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        del query
        return PerceptionSnapshot(
            mode=PerceptionMode.USER_QUERY,
            intent="document_lookup",
            domain="portfolio_documents",
            result_requirement="grounded_answer",
            required_capabilities=("QUERY_DOCUMENTS",),
            evidence_status=EvidenceStatus.NONE,
            local_goal_status=GoalStatus.PENDING,
            global_goal_status=GoalStatus.PENDING,
            confidence=1.0,
            reason_code="QUERY_CLASSIFIED",
        )

    async def perceive_step_result(
        self,
        *,
        query: str,
        previous: PerceptionSnapshot,
        observation: StructuredObservation,
    ) -> PerceptionSnapshot:
        del query, previous
        sufficient = bool(observation.evidence)
        return PerceptionSnapshot(
            mode=PerceptionMode.STEP_RESULT,
            intent="document_lookup",
            domain="portfolio_documents",
            result_requirement="grounded_answer",
            required_capabilities=("QUERY_DOCUMENTS",),
            evidence_status=(
                EvidenceStatus.SUFFICIENT if sufficient else EvidenceStatus.INSUFFICIENT
            ),
            local_goal_status=GoalStatus.ADVANCED,
            global_goal_status=GoalStatus.SATISFIED if sufficient else GoalStatus.BLOCKED,
            confidence=1.0,
            reason_code="EVIDENCE_SUFFICIENT" if sufficient else "EVIDENCE_INSUFFICIENT",
        )

    async def decide_initial(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        del perception
        if SEARCH_TOOL not in permitted_tools:
            return self._terminal(ActionType.REFUSE, version=1)
        action = Action(
            type=ActionType.TOOL_CALL,
            action_name=SEARCH_TOOL,
            arguments={"query": query, "top_k": 5},
            reason_code="SEARCH_AUTHORIZED_EVIDENCE",
        )
        return self._decision(action, version=1)

    async def decide_mid_session(
        self,
        *,
        query: str,
        perception: PerceptionSnapshot,
        current_plan: Plan,
        completed_steps: tuple[Step, ...],
        permitted_tools: frozenset[str],
    ) -> DecisionResult:
        del query, current_plan, completed_steps, permitted_tools
        action_type = (
            ActionType.FINALIZE
            if perception.evidence_status == EvidenceStatus.SUFFICIENT
            else ActionType.CLARIFY
        )
        return self._terminal(action_type, version=2)

    @staticmethod
    def _decision(action: Action, *, version: int) -> DecisionResult:
        return DecisionResult(
            plan=Plan(
                version=version,
                steps=(
                    Step(
                        step_index=0,
                        action_type=action.type,
                        action_name=action.action_name,
                        reason_code=action.reason_code,
                    ),
                ),
                change_reason_code="PLAN_CREATED",
            ),
            next_action=action,
        )

    @classmethod
    def _terminal(cls, action_type: ActionType, *, version: int) -> DecisionResult:
        return cls._decision(
            Action(type=action_type, reason_code=f"{action_type.value}_CONTROLLED"),
            version=version,
        )
