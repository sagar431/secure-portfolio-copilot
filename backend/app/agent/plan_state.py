from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from app.agent.models import (
    Action,
    CompletedStep,
    DecisionResult,
    Plan,
    Step,
    StepStatus,
)


class PlanContractError(ValueError):
    """A model-produced plan or action violated a host-owned invariant."""


class PlanExhaustedError(PlanContractError):
    """The model proposed an action when no executable plan step remained."""


def _action_fingerprint(action: Action) -> str:
    payload = {
        "type": action.type.value,
        "action_name": action.action_name,
        "arguments": action.arguments.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _plan_signature(plan: Plan) -> tuple[object, ...]:
    return (
        plan.plan_text,
        tuple(
            (step.step_index, step.action_type, step.action_name, step.status)
            for step in plan.steps
        ),
    )


@dataclass(frozen=True, slots=True)
class PlanState:
    """Owns plan versions, progression, and immutable completed-step history."""

    current_plan: Plan
    versions: tuple[Plan, ...]
    completed_history: tuple[CompletedStep, ...] = ()
    executed_action_fingerprints: frozenset[str] = frozenset()

    @classmethod
    def initial(cls, decision: DecisionResult) -> PlanState:
        if decision.plan.version != 1:
            raise PlanContractError("The initial plan version must be one")
        if decision.replan:
            raise PlanContractError("An initial plan cannot be a replan")
        if any(step.status != StepStatus.PENDING for step in decision.plan.steps):
            raise PlanContractError("Initial plan steps must be pending")
        state = cls(current_plan=decision.plan, versions=(decision.plan,))
        state.validate_next_action(decision.next_action)
        return state

    @property
    def first_pending_step(self) -> Step | None:
        return next(
            (step for step in self.current_plan.steps if step.status == StepStatus.PENDING),
            None,
        )

    def validate_next_action(self, action: Action) -> Step:
        step = self.first_pending_step
        if step is None:
            raise PlanExhaustedError("No executable pending step remains")
        if step.action_type != action.type or step.action_name != action.action_name:
            raise PlanContractError("The next action must match the first pending step")
        if _action_fingerprint(action) in self.executed_action_fingerprints:
            raise PlanContractError("A completed action cannot execute again")
        return step

    def complete_next(self, action: Action) -> PlanState:
        matched = self.validate_next_action(action)
        completed = matched.model_copy(
            update={"status": StepStatus.COMPLETED, "reason_code": "TOOL_COMPLETED"}
        )
        steps = tuple(
            completed if item.step_index == matched.step_index else item
            for item in self.current_plan.steps
        )
        updated_plan = self.current_plan.model_copy(update={"steps": steps})
        completed_record = CompletedStep(
            plan_version=self.current_plan.version,
            step_index=completed.step_index,
            action_type=completed.action_type,
            action_name=completed.action_name,
            reason_code=completed.reason_code,
        )
        return replace(
            self,
            current_plan=updated_plan,
            versions=self.versions[:-1] + (updated_plan,),
            completed_history=self.completed_history + (completed_record,),
            executed_action_fingerprints=self.executed_action_fingerprints
            | {_action_fingerprint(action)},
        )

    def apply_decision(self, decision: DecisionResult) -> tuple[PlanState, bool]:
        candidate = decision.plan
        changed = _plan_signature(candidate) != _plan_signature(self.current_plan)
        if changed:
            if candidate.version != self.current_plan.version + 1:
                raise PlanContractError("A changed plan must increment its version by exactly one")
            if any(step.status != StepStatus.PENDING for step in candidate.steps):
                raise PlanContractError("A new plan cannot rewrite completed-step history")
            state = replace(
                self,
                current_plan=candidate,
                versions=self.versions + (candidate,),
            )
        else:
            if candidate.version != self.current_plan.version:
                raise PlanContractError("An unchanged plan must retain its version")
            if decision.replan:
                raise PlanContractError("An unchanged plan cannot claim a replan")
            state = self
        state.validate_next_action(decision.next_action)
        return state, changed
