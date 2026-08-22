import { useEffect, useState } from 'react'

import { getAgentRun, listAgentRuns } from '../api/agentHistory'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { StoredAgentTimeline } from '../components/StoredAgentTimeline'
import type {
  AgentRunHistoryDetail,
  AgentRunHistorySummary,
} from '../types/agentHistory'

function label(value: string) {
  return value.replaceAll('_', ' ').toLowerCase()
}

function safeMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 403) {
    return 'Agent history is not available for this account.'
  }
  return 'Agent history could not be loaded safely.'
}

export function AgentHistoryPage() {
  const auth = useAuth()
  const token = auth.accessToken
  const [runs, setRuns] = useState<AgentRunHistorySummary[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [details, setDetails] = useState<Record<string, AgentRunHistoryDetail>>(
    {},
  )
  const [detailLoading, setDetailLoading] = useState<string | null>(null)
  const [inaccessibleRunId, setInaccessibleRunId] = useState<string | null>(
    null,
  )

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    listAgentRuns(token, null, controller.signal)
      .then((response) => {
        setRuns(response.data.runs)
        setNextCursor(response.data.next_cursor)
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
          setError(safeMessage(reason))
        }
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [token])

  async function loadMore() {
    if (!token || !nextCursor || loadingMore) return
    setLoadingMore(true)
    setError(null)
    try {
      const response = await listAgentRuns(token, nextCursor)
      setRuns((current) => [...current, ...response.data.runs])
      setNextCursor(response.data.next_cursor)
    } catch (reason) {
      setError(safeMessage(reason))
    } finally {
      setLoadingMore(false)
    }
  }

  async function toggle(runId: string) {
    if (expandedRunId === runId) {
      setExpandedRunId(null)
      return
    }
    setExpandedRunId(runId)
    setInaccessibleRunId(null)
    if (!token || details[runId]) return
    setDetailLoading(runId)
    try {
      const response = await getAgentRun(token, runId)
      setDetails((current) => ({ ...current, [runId]: response.data }))
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) {
        setInaccessibleRunId(runId)
      } else {
        setError(safeMessage(reason))
      }
    } finally {
      setDetailLoading(null)
    }
  }

  return (
    <section
      className="agent-history-page"
      aria-labelledby="agent-history-title"
    >
      <div className="page-heading">
        <div>
          <p className="eyebrow">Persistent agent runs</p>
          <h1 id="agent-history-title">Agent History</h1>
          <p className="supporting-copy">
            Reopen sanitized orchestration metadata without exposing prompts,
            reasoning, raw tool arguments, or document text.
          </p>
        </div>
        <aside className="security-note">
          <strong>Ownership is enforced by the server.</strong>
          <span>Unknown and foreign run IDs are indistinguishable.</span>
        </aside>
      </div>

      {loading ? <p role="status">Loading agent history…</p> : null}
      {error ? (
        <p className="degraded-state" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && !error && runs.length === 0 ? (
        <section className="chat-state-card" aria-label="Empty agent history">
          <h2>No agent runs yet</h2>
          <p>
            Bounded agent runs will appear here after they reach a safe recorded
            state.
          </p>
        </section>
      ) : null}

      <div className="agent-history-list">
        {runs.map((run) => (
          <article className="agent-history-card" key={run.id}>
            <header>
              <div>
                <span className="status-badge">{label(run.status)}</span>
                <h2>Run {run.id.slice(0, 8)}</h2>
              </div>
              <time dateTime={run.created_at}>
                {new Date(run.created_at).toLocaleString()}
              </time>
            </header>
            <dl className="agent-history-summary">
              <div>
                <dt>Response mode</dt>
                <dd>{label(run.response_mode)}</dd>
              </div>
              <div>
                <dt>Agent control</dt>
                <dd>{label(run.agent_control_mode)}</dd>
              </div>
              <div>
                <dt>Model tier</dt>
                <dd>
                  {run.selected_model_tier
                    ? label(run.selected_model_tier)
                    : 'No model call'}
                </dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd>{run.duration_ms} ms</dd>
              </div>
              <div>
                <dt>Reason</dt>
                <dd>{run.safe_reason_code}</dd>
              </div>
            </dl>
            <button type="button" onClick={() => void toggle(run.id)}>
              {expandedRunId === run.id
                ? 'Hide timeline'
                : 'View safe timeline'}
            </button>
            {expandedRunId === run.id && detailLoading === run.id ? (
              <p role="status">Loading safe timeline…</p>
            ) : null}
            {expandedRunId === run.id && inaccessibleRunId === run.id ? (
              <p className="degraded-state" role="alert">
                This agent run is unavailable.
              </p>
            ) : null}
            {expandedRunId === run.id && details[run.id] ? (
              <StoredAgentTimeline run={details[run.id]} />
            ) : null}
          </article>
        ))}
      </div>

      {nextCursor ? (
        <button
          type="button"
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? 'Loading more…' : 'Load more runs'}
        </button>
      ) : null}
    </section>
  )
}
