import type { AgentRunHistoryDetail } from '../types/agentHistory'

function label(value: string) {
  return value.replaceAll('_', ' ').toLowerCase()
}

export function StoredAgentTimeline({ run }: { run: AgentRunHistoryDetail }) {
  return (
    <section
      className="agent-trace stored-agent-trace"
      aria-label="Stored safe agent timeline"
    >
      <header className="agent-trace__heading">
        <div>
          <p className="eyebrow">Persistent safe history</p>
          <h3>Perception → Policy → Decision → Tool → Observation → Final</h3>
        </div>
        <span className="agent-trace__terminal">{label(run.status)}</span>
      </header>
      <ol
        className="agent-trace__events"
        aria-label="Stored agent trace events"
      >
        {run.timeline.map((event) => (
          <li key={event.sequence}>
            <div className="agent-trace__event-heading">
              <div>
                <span className="agent-trace__event-type">
                  {label(event.stage)}
                </span>
                <strong>{label(event.status)}</strong>
              </div>
              <span>{event.duration_ms} ms</span>
            </div>
            <p>{event.summary}</p>
            <dl className="agent-trace__event-details">
              <div>
                <dt>Reason code</dt>
                <dd>{event.safe_reason_code}</dd>
              </div>
              {event.step_number ? (
                <div>
                  <dt>Step</dt>
                  <dd>{event.step_number}</dd>
                </div>
              ) : null}
              {event.tool_name ? (
                <div>
                  <dt>Approved tool</dt>
                  <dd>{event.tool_name}</dd>
                </div>
              ) : null}
            </dl>
          </li>
        ))}
      </ol>
      <p className="agent-trace__boundary">
        Stored history contains bounded statuses, reason codes, approved tool
        names, and authorized identifiers only. Questions, prompts, reasoning,
        arguments, excerpts, memory content, and authorization objects are not
        retained here.
      </p>
    </section>
  )
}
