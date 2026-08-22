import { useState } from 'react'

import type { AgentApprovalState } from '../types/chat'

interface AgentApprovalCardProps {
  approval: AgentApprovalState
  resolving: boolean
  onApprove: () => void
  onReject: () => void
  onStop: () => void
  onChangeRequest: (content: string) => void
}

function label(value: string) {
  return value.replaceAll('_', ' ').toLowerCase()
}

export function AgentApprovalCard({
  approval,
  resolving,
  onApprove,
  onReject,
  onStop,
  onChangeRequest,
}: AgentApprovalCardProps) {
  const [changing, setChanging] = useState(false)
  const [change, setChange] = useState('')
  const expired = Date.parse(approval.expires_at) <= Date.now()
  const unavailable = resolving || expired || approval.status !== 'PENDING'

  return (
    <section
      className="approval-card"
      aria-labelledby={`approval-${approval.approval_id}`}
    >
      <header>
        <div>
          <p className="eyebrow">Agent approval required</p>
          <h3 id={`approval-${approval.approval_id}`}>
            {approval.action_label}
          </h3>
        </div>
        <span className="status-badge">
          {label(expired ? 'EXPIRED' : approval.status)}
        </span>
      </header>
      <p>{approval.safe_explanation}</p>
      <dl>
        <div>
          <dt>Approved tool</dt>
          <dd>{approval.tool_name}</dd>
        </div>
        <div>
          <dt>Risk level</dt>
          <dd>{label(approval.risk_level)}</dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>{approval.safe_scope_summary}</dd>
        </div>
        <div>
          <dt>Resource</dt>
          <dd>{approval.resource_type}</dd>
        </div>
        <div>
          <dt>Estimated cost</dt>
          <dd>{approval.estimated_cost_class}</dd>
        </div>
        <div>
          <dt>Remaining budget</dt>
          <dd>
            {approval.remaining_budget.steps} steps ·{' '}
            {approval.remaining_budget.tools} tools
          </dd>
        </div>
        <div>
          <dt>Expires</dt>
          <dd>
            <time dateTime={approval.expires_at}>
              {new Date(approval.expires_at).toLocaleString()}
            </time>
          </dd>
        </div>
      </dl>
      {expired ? (
        <p role="status">This approval has expired. The action cannot run.</p>
      ) : null}
      {changing ? (
        <div className="approval-card__change">
          <label htmlFor={`change-${approval.approval_id}`}>
            Changed request
          </label>
          <textarea
            id={`change-${approval.approval_id}`}
            value={change}
            maxLength={1000}
            disabled={unavailable}
            onChange={(event) => setChange(event.target.value)}
          />
          <button
            type="button"
            disabled={unavailable || change.trim().length === 0}
            onClick={() => onChangeRequest(change)}
          >
            Submit changed request
          </button>
        </div>
      ) : null}
      <div className="approval-card__actions">
        <button
          type="button"
          className="primary-button"
          disabled={unavailable}
          onClick={onApprove}
        >
          {resolving ? 'Resolving…' : 'Approve once'}
        </button>
        <button type="button" disabled={unavailable} onClick={onReject}>
          Reject
        </button>
        <button
          type="button"
          disabled={unavailable}
          onClick={() => setChanging(true)}
        >
          Change request
        </button>
        <button type="button" disabled={unavailable} onClick={onStop}>
          Stop run
        </button>
      </div>
      <p className="agent-trace__boundary">
        Approval applies to this one allow-listed action only. Raw arguments,
        prompts, document content, and authorization internals are not
        displayed.
      </p>
    </section>
  )
}
