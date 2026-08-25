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
from app.chat.contracts import GroundedAgentContext, GroundedMemory
from app.mcp_gateway.contracts import (
    CalculateCagrInput,
    CalculateFinancialMetricInput,
    FinancialMetricName,
    GetDocumentExcerptInput,
    PermittedToolDescriptor,
    ProposeMemoryInput,
    QueryFinancialMetricsInput,
    SearchAuthorizedDocumentsInput,
    SearchMemoryInput,
)

SEARCH_TOOL = "portfolio.search_authorized_documents"
CALCULATOR_BY_PHRASE = {
    "ebitda margin": "portfolio.calculate_ebitda_margin",
    "revenue growth": "portfolio.calculate_revenue_growth",
    "net profit margin": "portfolio.calculate_net_profit_margin",
    "debt to equity": "portfolio.calculate_debt_to_equity",
    "debt-to-equity": "portfolio.calculate_debt_to_equity",
    "cash runway": "portfolio.calculate_cash_runway",
    "cagr": "portfolio.calculate_cagr",
}


class RuleBasedFakeAgentProvider:
    """Deterministic test-only Perception and Decision provider."""

    model_name = "fake-agent-stages-v1"

    def __init__(self) -> None:
        self.memories: tuple[GroundedMemory, ...] = ()
        self.request_context = GroundedAgentContext()
        self._last_observation: StructuredObservation | None = None

    def bind_request_context(self, context: GroundedAgentContext) -> None:
        # Exercise the production context-binding seam without changing fake decisions.
        self.request_context = context
        self.memories = context.memories

    async def perceive_user_query(self, *, query: str) -> PerceptionSnapshot:
        normalized = query.casefold()
        if any(
            phrase in normalized
            for phrase in ("remember that", "remember this", "i prefer", "from now on")
        ):
            intent = PerceptionIntent.MEMORY_WRITE
            required_evidence = (RequiredEvidence.MEMORY_CONTEXT,)
        elif any(
            phrase in normalized for phrase in ("remember last", "investigate last", "memory")
        ):
            intent = PerceptionIntent.MEMORY_RECALL
            required_evidence = (RequiredEvidence.MEMORY_CONTEXT,)
        elif (
            "calculate" in normalized
            or "compute" in normalized
            or any(phrase in normalized for phrase in CALCULATOR_BY_PHRASE)
        ):
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
        del current_plan, completed_steps, remaining_budgets
        self._last_observation = observation
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
        company_slug = "atlas-main" if "atlas" in normalized else "orion-main"
        period_match = re.search(r"\bfy(\d{4})\b", normalized)
        period = f"FY{period_match.group(1)}" if period_match else "FY2025"
        if "remember" in normalized and "portfolio.propose_memory" in permitted:
            action = Action(
                type=ActionType.TOOL_CALL,
                action_name="portfolio.propose_memory",
                arguments=ProposeMemoryInput(
                    content=query[:500],
                    normalized_key="agent_proposed_preference",
                    explicit=True,
                ),
                reason_code="PROPOSE_MEMORY_TO_HOST_POLICY",
            )
            return self._decision(action, version=1)
        if any(
            phrase in normalized for phrase in ("remember last", "investigate last", "memory")
        ) and ("portfolio.search_memory" in permitted):
            action = Action(
                type=ActionType.TOOL_CALL,
                action_name="portfolio.search_memory",
                arguments=SearchMemoryInput(query=query, mode="latest_episode", top_k=1),
                reason_code="SEARCH_AUTHORIZED_MEMORY",
            )
            return self._decision(action, version=1)
        calculator = next(
            (tool for phrase, tool in CALCULATOR_BY_PHRASE.items() if phrase in normalized),
            None,
        )
        if calculator is not None and calculator in permitted:
            arguments: CalculateCagrInput | CalculateFinancialMetricInput
            if calculator == "portfolio.calculate_cagr":
                periods = re.findall(r"\bfy(\d{4})\b", normalized)
                start = f"FY{periods[0]}" if len(periods) >= 2 else f"FY{int(period[2:]) - 1}"
                end = f"FY{periods[-1]}" if len(periods) >= 2 else period
                arguments = CalculateCagrInput(
                    company_slug=company_slug,
                    start_period=start,
                    end_period=end,
                )
            else:
                arguments = CalculateFinancialMetricInput(
                    company_slug=company_slug,
                    reporting_period=period,
                )
            action = Action(
                type=ActionType.TOOL_CALL,
                action_name=calculator,
                arguments=arguments,
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
        direct_metric = next(
            (
                metric
                for phrase, metric in (
                    ("closing cash", FinancialMetricName.CLOSING_CASH),
                    ("bank debt", FinancialMetricName.BANK_DEBT),
                    ("net profit", FinancialMetricName.NET_PROFIT),
                    ("ebitda", FinancialMetricName.EBITDA),
                    ("revenue", FinancialMetricName.REVENUE),
                )
                if phrase in normalized
            ),
            None,
        )
        if direct_metric is not None and "portfolio.query_financial_metrics" in permitted:
            action = Action(
                type=ActionType.TOOL_CALL,
                action_name="portfolio.query_financial_metrics",
                arguments=QueryFinancialMetricsInput(
                    company_slug=company_slug,
                    reporting_period=period,
                    metric=direct_metric,
                ),
                reason_code="QUERY_AUTHORIZED_FINANCIAL_METRIC",
            )
            return self._decision(action, version=1)
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
        del completed_steps
        normalized = query.casefold()
        permitted = {item.name.value for item in permitted_tool_catalog}
        if (
            any(phrase in normalized for phrase in ("exact excerpt", "verbatim excerpt"))
            and self._last_observation is not None
            and self._last_observation.tool_name == SEARCH_TOOL
            and self._last_observation.evidence
            and "portfolio.get_document_excerpt" in permitted
        ):
            source = self._last_observation.evidence[0]
            excerpt = Action(
                type=ActionType.TOOL_CALL,
                action_name="portfolio.get_document_excerpt",
                arguments=GetDocumentExcerptInput(
                    document_id=source.document_id,
                    chunk_id=source.chunk_id,
                ),
                reason_code="GET_EXACT_AUTHORIZED_EXCERPT",
            )
            finalize = Action(
                type=ActionType.FINALIZE,
                reason_code="FINALIZE_GROUNDED_ANSWER",
            )
            return DecisionResult(
                plan=Plan(
                    version=current_plan.version + 1,
                    plan_text=("Read the exact authorized excerpt.", "Finalize with citation."),
                    steps=(
                        Step(
                            step_index=0,
                            action_type=excerpt.type,
                            action_name=excerpt.action_name,
                            reason_code=excerpt.reason_code,
                        ),
                        Step(
                            step_index=1,
                            action_type=finalize.type,
                            reason_code=finalize.reason_code,
                        ),
                    ),
                    change_reason_code="EXACT_EXCERPT_REQUIRED",
                ),
                next_action=excerpt,
                replan=True,
            )
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
