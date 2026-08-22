from app.models.agent_runs import AgentRunStatus


class InvalidAgentRunTransition(ValueError):
    """A caller attempted to bypass the host-owned run state machine."""


TERMINAL_AGENT_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.REFUSED,
        AgentRunStatus.CLARIFICATION_REQUIRED,
        AgentRunStatus.INSUFFICIENT_EVIDENCE,
        AgentRunStatus.LIMIT_REACHED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }
)

_ALLOWED_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.CREATED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.REFUSED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
        }
    ),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.AWAITING_APPROVAL,
            *TERMINAL_AGENT_RUN_STATUSES,
        }
    ),
    AgentRunStatus.AWAITING_APPROVAL: frozenset(
        {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}
    ),
    **{status: frozenset() for status in TERMINAL_AGENT_RUN_STATUSES},
}


def validate_agent_run_transition(
    current: AgentRunStatus, target: AgentRunStatus
) -> AgentRunStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidAgentRunTransition(f"Invalid agent run transition: {current} -> {target}")
    return target
