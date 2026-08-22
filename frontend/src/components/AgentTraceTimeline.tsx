import type { AgentRunData, GroundedCitationData } from '../types/chat'

interface AgentTraceTimelineProps {
  run: AgentRunData
  onOpenEvidence: (citation: GroundedCitationData) => void
}

function displayLabel(value: string) {
  return value.replaceAll('_', ' ')
}

export function AgentTraceTimeline({
  run,
  onOpenEvidence,
}: AgentTraceTimelineProps) {
  const citationsById = new Map(
    run.citations.map((citation) => [citation.citation_id, citation]),
  )

  return (
    <section
      className="agent-trace"
      aria-labelledby={`agent-trace-${run.agent_session_id}`}
    >
      <header className="agent-trace__heading">
        <div>
          <p className="eyebrow">Sanitized agent trace</p>
          <h3 id={`agent-trace-${run.agent_session_id}`}>
            Bounded orchestration timeline
          </h3>
        </div>
        <span className="agent-trace__terminal">
          {displayLabel(run.terminal_status)}
        </span>
      </header>

      <dl className="agent-trace__summary">
        <div>
          <dt>Requested mode</dt>
          <dd>{displayLabel(run.requested_response_mode)}</dd>
        </div>
        {run.resolved_response_mode ? (
          <div>
            <dt>Selected mode</dt>
            <dd>{displayLabel(run.resolved_response_mode)}</dd>
          </div>
        ) : null}
        {run.model_name ? (
          <div>
            <dt>Model route</dt>
            <dd>{run.model_name}</dd>
          </div>
        ) : null}
        <div>
          <dt>Session ID</dt>
          <dd>{run.agent_session_id}</dd>
        </div>
        <div>
          <dt>Stopping reason</dt>
          <dd>{run.stopping_reason}</dd>
        </div>
        <div>
          <dt>Steps</dt>
          <dd>{run.step_count}</dd>
        </div>
        <div>
          <dt>Replans</dt>
          <dd>{run.replan_count}</dd>
        </div>
        <div>
          <dt>Retries</dt>
          <dd>{run.retry_count}</dd>
        </div>
      </dl>

      <ol className="agent-trace__events" aria-label="Agent trace events">
        {run.trace.map((event) => (
          <li key={event.event_id}>
            <div className="agent-trace__event-heading">
              <div>
                <span className="agent-trace__event-type">
                  {displayLabel(event.event_type)}
                </span>
                <strong>{displayLabel(event.status)}</strong>
              </div>
              <span>{event.duration_ms} ms</span>
            </div>
            <dl className="agent-trace__event-details">
              <div>
                <dt>Event ID</dt>
                <dd>{event.event_id}</dd>
              </div>
              {event.action_name ? (
                <div>
                  <dt>Action</dt>
                  <dd>{event.action_name}</dd>
                </div>
              ) : null}
              {event.reason_code ? (
                <div>
                  <dt>Reason code</dt>
                  <dd>{event.reason_code}</dd>
                </div>
              ) : null}
            </dl>
            {event.evidence_reference_ids.length > 0 ? (
              <div className="agent-trace__evidence">
                <span>Evidence references</span>
                <div>
                  {event.evidence_reference_ids.map((referenceId) => {
                    const citation = citationsById.get(referenceId)
                    return citation ? (
                      <button
                        key={referenceId}
                        type="button"
                        onClick={() => onOpenEvidence(citation)}
                      >
                        {referenceId}
                      </button>
                    ) : (
                      <code key={referenceId}>{referenceId}</code>
                    )
                  })}
                </div>
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      <p className="agent-trace__boundary">
        This timeline contains approved identifiers and status metadata only.
        Prompts, reasoning, tool arguments, authorization scope, and evidence
        content are excluded.
      </p>
    </section>
  )
}
