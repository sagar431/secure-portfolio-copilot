import re

from app.agent.models import (
    Action,
    ActionType,
    CompletedStep,
    DecisionResult,
    EvidenceStatus,
    GoalStatus,
    PerceptionEntities,
    PerceptionIntent,
    PerceptionMode,
    PerceptionSnapshot,
    Plan,
    RemainingBudgets,
    RequiredEvidence,
    ResultRequirement,
    Step,
    StructuredObservation,
)
from app.mcp_gateway.contracts import (
    CalculateFinancialMetricInput,
    PermittedToolDescriptor,
    SearchAuthorizedDocumentsInput,
)

SEARCH_TOOL = "portfolio.search_authorized_documents"
CALCULATOR_BY_PHRASE = {
    "ebitda margin": "portfolio.calculate_ebitda_margin",
    "revenue growth": "portfolio.calculate_revenue_growth",
    "net profit margin": "portfolio.calculate_net_profit_margin",
}


class RuleBasedFakeAgentProvider:
    """Deterministic test-only Perception and Decision provider."""

    model_name = "fake-agent-stages-v1"

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        normalized = query.casefold()
        if "calculate" in normalized or "margin" in normalized:
            intent = PerceptionIntent.CALCULATION_REQUIRED
            required_evidence = (RequiredEvidence.CALCULATION_INPUTS,)
        elif "legal" in normalized or "contract" in normalized:
            intent = PerceptionIntent.LEGAL_LOOKUP
            required_evidence = (RequiredEvidence.LEGAL_DOCUMENT,)
        elif "compare" in normalized:
            intent = PerceptionIntent.PORTFOLIO_COMPARISON
            required_evidence = (RequiredEvidence.COMPARISON_DOCUMENTS,)
        else:
            intent = PerceptionIntent.FINANCIAL_LOOKUP
            required_evidence = (RequiredEvidence.FINANCIAL_DOCUMENT,)
        return PerceptionSnapshot(
            mode=PerceptionMode.USER_QUERY,
            intent=intent,
            domain="portfolio_documents",
            entities=PerceptionEntities(),
            result_requirement=ResultRequirement.GROUNDED_ANSWER,
            required_evidence=required_evidence,
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
        current_plan: Plan,
        completed_steps: tuple[CompletedStep, ...],
        observation: StructuredObservation,
        remaining_budgets: RemainingBudgets,
    ) -> PerceptionSnapshot:
        del query, current_plan, completed_steps, remaining_budgets
        sufficient = bool(observation.evidence)
        return PerceptionSnapshot(
            mode=PerceptionMode.STEP_RESULT,
            intent=previous.intent,
            domain="portfolio_documents",
            entities=previous.entities,
            mentioned_scope_hints=previous.mentioned_scope_hints,
            result_requirement=previous.result_requirement,
            required_evidence=previous.required_evidence,
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
        permitted_tool_catalog: tuple[PermittedToolDescriptor, ...],
    ) -> DecisionResult:
        del perception
        permitted = {item.name.value for item in permitted_tool_catalog}
        normalized = query.casefold()
        calculator = next(
            (tool for phrase, tool in CALCULATOR_BY_PHRASE.items() if phrase in normalized),
            None,
        )
        if calculator is not None and calculator in permitted:
            period_match = re.search(r"\bfy(\d{4})\b", normalized)
            period = f"FY{period_match.group(1)}" if period_match else "FY2025"
            company_slug = "atlas-main" if "atlas" in normalized else "orion-main"
            action = Action(
                type=ActionType.TOOL_CALL,
                action_name=calculator,
                arguments=CalculateFinancialMetricInput(
                    company_slug=company_slug,
                    reporting_period=period,
                ),
                reason_code="CALCULATE_AUTHORIZED_METRIC",
            )
            return DecisionResult(
                plan=Plan(
                    version=1,
                    plan_text=("Calculate from reauthorized structured inputs.",),
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
        if SEARCH_TOOL not in permitted:
            return self._terminal(ActionType.REFUSE, version=1)
        action = Action(
            type=ActionType.TOOL_CALL,
            action_name=SEARCH_TOOL,
            arguments=SearchAuthorizedDocumentsInput(query=query, top_k=5),
            reason_code="SEARCH_AUTHORIZED_EVIDENCE",
        )
        finalize = Action(type=ActionType.FINALIZE, reason_code="FINALIZE_GROUNDED_ANSWER")
        return DecisionResult(
            plan=Plan(
                version=1,
                plan_text=("Search authorized documents.", "Finalize from validated evidence."),
                steps=(
                    Step(
                        step_index=0,
                        action_type=action.type,
                        action_name=action.action_name,
                        reason_code=action.reason_code,
                    ),
                    Step(
                        step_index=1,
                        action_type=finalize.type,
                        reason_code=finalize.reason_code,
                    ),
                ),
                change_reason_code="PLAN_CREATED",
            ),
            next_action=action,
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
        del query, completed_steps, permitted_tool_catalog
        action_type = (
            ActionType.FINALIZE
            if perception.evidence_status == EvidenceStatus.SUFFICIENT
            else ActionType.CLARIFY
        )
        action = Action(type=action_type, reason_code=f"{action_type.value}_CONTROLLED")
        if action_type == ActionType.FINALIZE:
            return DecisionResult(plan=current_plan, next_action=action)
        return self._terminal(action_type, version=current_plan.version + 1)

    @staticmethod
    def _decision(action: Action, *, version: int) -> DecisionResult:
        return DecisionResult(
            plan=Plan(
                version=version,
                plan_text=(f"Perform controlled {action.type.value.casefold()}.",),
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
