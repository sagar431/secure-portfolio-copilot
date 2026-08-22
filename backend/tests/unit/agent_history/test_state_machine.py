import pytest

from app.agent.run_state import InvalidAgentRunTransition, validate_agent_run_transition
from app.models.agent_runs import AgentRunStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentRunStatus.CREATED, AgentRunStatus.RUNNING),
        (AgentRunStatus.CREATED, AgentRunStatus.REFUSED),
        (AgentRunStatus.RUNNING, AgentRunStatus.AWAITING_APPROVAL),
        (AgentRunStatus.AWAITING_APPROVAL, AgentRunStatus.RUNNING),
        (AgentRunStatus.AWAITING_APPROVAL, AgentRunStatus.CANCELLED),
        *(
            (AgentRunStatus.RUNNING, terminal)
            for terminal in (
                AgentRunStatus.COMPLETED,
                AgentRunStatus.REFUSED,
                AgentRunStatus.CLARIFICATION_REQUIRED,
                AgentRunStatus.INSUFFICIENT_EVIDENCE,
                AgentRunStatus.LIMIT_REACHED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            )
        ),
    ],
)
def test_allowed_state_transitions(current: AgentRunStatus, target: AgentRunStatus) -> None:
    assert validate_agent_run_transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (AgentRunStatus.CREATED, AgentRunStatus.COMPLETED),
        (AgentRunStatus.RUNNING, AgentRunStatus.CREATED),
        (AgentRunStatus.AWAITING_APPROVAL, AgentRunStatus.COMPLETED),
        (AgentRunStatus.COMPLETED, AgentRunStatus.RUNNING),
        (AgentRunStatus.FAILED, AgentRunStatus.RUNNING),
        (AgentRunStatus.CANCELLED, AgentRunStatus.CREATED),
    ],
)
def test_invalid_and_terminal_state_transitions_fail_closed(
    current: AgentRunStatus, target: AgentRunStatus
) -> None:
    with pytest.raises(InvalidAgentRunTransition):
        validate_agent_run_transition(current, target)
