import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import {
  createConversation,
  changeAgentRequest,
  listConversations,
  resolveAgentApproval,
  runConversationAgent,
  sendConversationMessage,
  stopAgentRun,
} from '../api/chat'
import { useAuth } from '../auth/useAuth'
import { AgentTraceTimeline } from '../components/AgentTraceTimeline'
import { AgentApprovalCard } from '../components/AgentApprovalCard'
import { CalculationCard } from '../components/CalculationCard'
import { EvidenceDrawer } from '../components/EvidenceDrawer'
import { GroundedAnswer } from '../components/GroundedAnswer'
import type {
  AgentRunData,
  AgentControlMode,
  AwaitingAgentApprovalData,
  ChatTurn,
  ConversationData,
  GroundedAnswerData,
  GroundedCitationData,
  ResponseMode,
} from '../types/chat'
import { CHAT_QUESTION_MAX_LENGTH } from '../types/chat'

const SUGGESTED_QUESTIONS = [
  'What changed in Orion’s operating margin?',
  'Summarize Orion’s approved financial results.',
  'What risks are documented for Orion Finance?',
] as const

type SafeErrorKind = 'denied' | 'timeout' | 'generic'

interface SafeError {
  kind: SafeErrorKind
  message: string
  requestId: string | null
}

const TIMEOUT_CODES = new Set([
  'llm_timeout',
  'provider_timeout',
  'generation_timeout',
  'agent_timeout',
  'tool_timeout',
  'duration_exceeded',
])
const DENIAL_CODES = new Set([
  'forbidden',
  'authorization_denied',
  'conversation_not_found',
  'scope_denied',
  'tool_authorization_denied',
])

type SubmissionMode = 'grounded' | 'agent'

interface UpgradeRequest {
  conversationId: string
  content: string
  submissionMode: SubmissionMode
}

function safeError(error: unknown): SafeError {
  if (error instanceof ApiError) {
    if (error.code === 'approval_expired') {
      return {
        kind: 'generic',
        message: 'This approval expired. The action was not executed.',
        requestId: error.requestId,
      }
    }
    if (
      error.code === 'approval_unavailable' ||
      error.code === 'approval_mismatch' ||
      error.code === 'authorization_changed'
    ) {
      return {
        kind: 'denied',
        message:
          'The pending action could not be resumed safely and was not executed.',
        requestId: error.requestId,
      }
    }
    if (TIMEOUT_CODES.has(error.code)) {
      return {
        kind: 'timeout',
        message:
          'The answer provider took too long. No partial answer or unvalidated citation is shown.',
        requestId: error.requestId,
      }
    }
    if (error.status === 403 || DENIAL_CODES.has(error.code)) {
      return {
        kind: 'denied',
        message:
          'This request is outside your current document access. No restricted evidence was returned.',
        requestId: error.requestId,
      }
    }
    return {
      kind: 'generic',
      message: 'The grounded answer could not be completed. Try again.',
      requestId: error.requestId,
    }
  }
  return {
    kind: 'generic',
    message: 'The grounded answer could not be completed. Try again.',
    requestId: null,
  }
}

function displayDate(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
  }).format(new Date(timestamp))
}

function ErrorCard({ error }: { error: SafeError }) {
  const title =
    error.kind === 'timeout'
      ? 'Answer provider timed out'
      : error.kind === 'denied'
        ? 'Request not authorized'
        : 'Safe answer unavailable'
  return (
    <section
      className={`chat-state-card chat-state-card--${error.kind}`}
      role="alert"
    >
      <p className="eyebrow">{error.kind}</p>
      <h3>{title}</h3>
      <p>{error.message}</p>
      {error.requestId ? <small>Request ID: {error.requestId}</small> : null}
    </section>
  )
}

function agentAnswer(run: AgentRunData): GroundedAnswerData {
  const hasGroundedClaims = run.claims.length > 0 && run.citations.length > 0
  return {
    conversation_id: run.conversation_id,
    user_message_id: run.user_message_id,
    assistant_message_id: run.assistant_message_id,
    status: hasGroundedClaims ? 'grounded' : 'insufficient_evidence',
    answer: run.answer,
    claims: run.claims,
    citations: run.citations,
    limitations: run.limitations,
    model_name: run.model_name,
    route_reason: run.route_reason,
    fallback_used: false,
    requested_response_mode: run.requested_response_mode,
    resolved_response_mode: run.resolved_response_mode,
    input_tokens: null,
    output_tokens: null,
    latency_ms: null,
    estimated_model_cost_usd: null,
    pricing_snapshot_date: null,
  }
}

export function ChatPage() {
  const auth = useAuth()
  const [conversations, setConversations] = useState<ConversationData[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [turnsByConversation, setTurnsByConversation] = useState<
    Record<string, ChatTurn[]>
  >({})
  const [question, setQuestion] = useState('')
  const [responseMode, setResponseMode] = useState<ResponseMode>('auto')
  const [agentControlMode, setAgentControlMode] =
    useState<AgentControlMode>('balanced')
  const [pendingApproval, setPendingApproval] = useState<{
    data: AwaitingAgentApprovalData
    question: string
  } | null>(null)
  const [approvalResolving, setApprovalResolving] = useState(false)
  const [approvalStatus, setApprovalStatus] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [creating, setCreating] = useState(false)
  const [sending, setSending] = useState(false)
  const [sendingMode, setSendingMode] = useState<SubmissionMode>('grounded')
  const [canceled, setCanceled] = useState(false)
  const [error, setError] = useState<SafeError | null>(null)
  const [upgradeRequest, setUpgradeRequest] = useState<UpgradeRequest | null>(
    null,
  )
  const [openCitation, setOpenCitation] = useState<GroundedCitationData | null>(
    null,
  )
  const activeRequest = useRef<AbortController | null>(null)

  const closeEvidence = useCallback(() => setOpenCitation(null), [])

  useEffect(() => {
    if (!auth.accessToken) {
      setLoadingList(false)
      return
    }
    const controller = new AbortController()
    void listConversations(auth.accessToken, controller.signal)
      .then((response) => {
        setConversations(response.data.conversations)
        setSelectedId(response.data.conversations[0]?.id ?? null)
      })
      .catch((listError: unknown) => {
        if (
          listError instanceof DOMException &&
          listError.name === 'AbortError'
        ) {
          return
        }
        setError(safeError(listError))
      })
      .finally(() => setLoadingList(false))
    return () => controller.abort()
  }, [auth.accessToken])

  useEffect(
    () => () => {
      activeRequest.current?.abort()
      activeRequest.current = null
    },
    [],
  )

  async function startConversation() {
    if (!auth.accessToken || creating || sending) {
      return
    }
    setCreating(true)
    setError(null)
    setUpgradeRequest(null)
    setCanceled(false)
    try {
      const response = await createConversation(auth.accessToken, null)
      const conversation = response.data.conversation
      setConversations((current) => [
        conversation,
        ...current.filter((item) => item.id !== conversation.id),
      ])
      setSelectedId(conversation.id)
      setQuestion('')
    } catch (createError) {
      setError(safeError(createError))
    } finally {
      setCreating(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitter = (event.nativeEvent as SubmitEvent).submitter
    const submissionMode =
      submitter instanceof HTMLButtonElement && submitter.value === 'agent'
        ? 'agent'
        : 'grounded'
    const content = question.trim()
    if (!content) {
      setError({
        kind: 'generic',
        message: 'Enter a question before asking the copilot.',
        requestId: null,
      })
      return
    }
    if (!auth.accessToken) {
      setError({
        kind: 'generic',
        message: 'Your authenticated session is unavailable. Sign in again.',
        requestId: null,
      })
      return
    }

    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    setSending(true)
    setSendingMode(submissionMode)
    setError(null)
    setUpgradeRequest(null)
    setCanceled(false)
    setOpenCitation(null)
    let conversationId = selectedId
    try {
      if (!conversationId) {
        const created = await createConversation(
          auth.accessToken,
          null,
          controller.signal,
        )
        const conversation = created.data.conversation
        conversationId = conversation.id
        setConversations((current) => [conversation, ...current])
        setSelectedId(conversation.id)
      }
      if (!conversationId) {
        throw new ApiError(
          'Conversation could not be created.',
          0,
          'invalid_conversation_id',
          null,
        )
      }
      const targetConversationId = conversationId
      let turn: ChatTurn | null = null
      if (submissionMode === 'agent') {
        const response = await runConversationAgent(
          auth.accessToken,
          targetConversationId,
          content,
          controller.signal,
          responseMode,
          agentControlMode,
        )
        if ('outcome' in response.data) {
          setPendingApproval({ data: response.data, question: content })
          setApprovalStatus(null)
        } else {
          turn = {
            kind: 'agent',
            id: response.data.assistant_message_id,
            question: content,
            response: response.data,
          }
        }
      } else {
        turn = await sendConversationMessage(
          auth.accessToken,
          targetConversationId,
          content,
          controller.signal,
          responseMode,
        ).then((response) => ({
          kind: 'grounded' as const,
          id: response.data.assistant_message_id,
          question: content,
          response: response.data,
        }))
      }
      if (turn) {
        setTurnsByConversation((current) => ({
          ...current,
          [targetConversationId]: [
            ...(current[targetConversationId] ?? []),
            turn,
          ],
        }))
      }
      setQuestion('')
    } catch (requestError) {
      if (
        requestError instanceof DOMException &&
        requestError.name === 'AbortError'
      ) {
        setCanceled(true)
        return
      }
      if (
        requestError instanceof ApiError &&
        requestError.status === 409 &&
        requestError.code === 'deep_mode_required' &&
        conversationId
      ) {
        setUpgradeRequest({ conversationId, content, submissionMode })
        return
      }
      setError(safeError(requestError))
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
        setSending(false)
      }
    }
  }

  function cancelRequest() {
    activeRequest.current?.abort()
  }

  async function resolvePending(action: 'approve_once' | 'reject') {
    if (!pendingApproval || !auth.accessToken || approvalResolving) return
    setApprovalResolving(true)
    setError(null)
    try {
      const response = await resolveAgentApproval(
        auth.accessToken,
        pendingApproval.data.agent_session_id,
        pendingApproval.data.approval.approval_id,
        action,
      )
      if ('terminal_status' in response.data) {
        const completed = response.data
        setTurnsByConversation((current) => ({
          ...current,
          [completed.conversation_id]: [
            ...(current[completed.conversation_id] ?? []),
            {
              kind: 'agent',
              id: completed.assistant_message_id,
              question: pendingApproval.question,
              response: completed,
            },
          ],
        }))
        setPendingApproval(null)
        setApprovalStatus('Run completed after one approved action.')
      } else if (response.data.outcome === 'awaiting_approval') {
        setPendingApproval({
          data: response.data,
          question: pendingApproval.question,
        })
        setApprovalStatus(
          'Approved action completed. The next action needs approval.',
        )
      } else {
        setPendingApproval(null)
        setApprovalStatus(response.data.safe_message)
      }
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        (reason.code === 'approval_expired' ||
          reason.code === 'approval_unavailable' ||
          reason.code === 'approval_mismatch' ||
          reason.code === 'authorization_changed')
      ) {
        setPendingApproval(null)
      }
      setError(safeError(reason))
    } finally {
      setApprovalResolving(false)
    }
  }

  async function stopPending() {
    if (!pendingApproval || !auth.accessToken || approvalResolving) return
    setApprovalResolving(true)
    try {
      const response = await stopAgentRun(
        auth.accessToken,
        pendingApproval.data.agent_session_id,
      )
      setApprovalStatus(response.data.safe_message)
      setPendingApproval(null)
    } catch (reason) {
      setError(safeError(reason))
    } finally {
      setApprovalResolving(false)
    }
  }

  async function submitChange(content: string) {
    if (!pendingApproval || !auth.accessToken || approvalResolving) return
    setApprovalResolving(true)
    try {
      const response = await changeAgentRequest(
        auth.accessToken,
        pendingApproval.data.agent_session_id,
        pendingApproval.data.approval.approval_id,
        content,
      )
      if ('outcome' in response.data) {
        setPendingApproval({ data: response.data, question: content.trim() })
        setApprovalStatus(
          'The old run was cancelled and a new bounded plan was created.',
        )
      } else {
        const completed = response.data
        setTurnsByConversation((current) => ({
          ...current,
          [completed.conversation_id]: [
            ...(current[completed.conversation_id] ?? []),
            {
              kind: 'agent',
              id: completed.assistant_message_id,
              question: content.trim(),
              response: completed,
            },
          ],
        }))
        setPendingApproval(null)
        setApprovalStatus('The changed request completed safely.')
      }
    } catch (reason) {
      setError(safeError(reason))
    } finally {
      setApprovalResolving(false)
    }
  }

  async function continueWithDeep() {
    if (!upgradeRequest || !auth.accessToken || sending) return
    const controller = new AbortController()
    activeRequest.current = controller
    setSending(true)
    setSendingMode(upgradeRequest.submissionMode)
    setError(null)
    try {
      let turn: ChatTurn | null = null
      if (upgradeRequest.submissionMode === 'agent') {
        const response = await runConversationAgent(
          auth.accessToken,
          upgradeRequest.conversationId,
          upgradeRequest.content,
          controller.signal,
          'deep',
          agentControlMode,
        )
        if ('outcome' in response.data) {
          setPendingApproval({
            data: response.data,
            question: upgradeRequest.content,
          })
        } else {
          turn = {
            kind: 'agent',
            id: response.data.assistant_message_id,
            question: upgradeRequest.content,
            response: response.data,
          }
        }
      } else {
        const response = await sendConversationMessage(
          auth.accessToken,
          upgradeRequest.conversationId,
          upgradeRequest.content,
          controller.signal,
          'deep',
        )
        turn = {
          kind: 'grounded',
          id: response.data.assistant_message_id,
          question: upgradeRequest.content,
          response: response.data,
        }
      }
      if (turn) {
        setTurnsByConversation((current) => ({
          ...current,
          [upgradeRequest.conversationId]: [
            ...(current[upgradeRequest.conversationId] ?? []),
            turn,
          ],
        }))
      }
      setQuestion('')
      setUpgradeRequest(null)
    } catch (requestError) {
      if (
        requestError instanceof DOMException &&
        requestError.name === 'AbortError'
      ) {
        setCanceled(true)
      } else {
        setError(safeError(requestError))
      }
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
        setSending(false)
      }
    }
  }

  const selectedConversation = conversations.find(
    (conversation) => conversation.id === selectedId,
  )
  const turns = selectedId ? (turnsByConversation[selectedId] ?? []) : []

  return (
    <div className="chat-page">
      <header className="chat-page-heading">
        <div>
          <p className="eyebrow">Authorized portfolio evidence</p>
          <h1>Grounded chat workspace</h1>
          <p className="hero-copy">
            Answers use only evidence retrieved inside your server-derived
            authorization scope. Every supported claim opens its exact source.
          </p>
        </div>
        <aside className="security-note">
          <strong>Documents are evidence, not instructions</strong>
          <span>
            The service validates authorization and citations before an answer
            is displayed. Unsupported questions receive an abstention.
          </span>
        </aside>
      </header>

      <div className="chat-workspace">
        <aside className="conversation-sidebar" aria-label="Conversations">
          <div className="conversation-sidebar__heading">
            <div>
              <p className="eyebrow">Your workspace</p>
              <h2>Conversations</h2>
            </div>
            <button
              type="button"
              className="primary-button conversation-new-button"
              disabled={creating || sending}
              onClick={() => void startConversation()}
            >
              {creating ? 'Creating…' : 'New'}
            </button>
          </div>
          {loadingList ? (
            <p className="conversation-list-state" role="status">
              Loading conversations…
            </p>
          ) : conversations.length === 0 ? (
            <p className="conversation-list-state">
              Your first question will start a conversation.
            </p>
          ) : (
            <div className="conversation-list">
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={
                    conversation.id === selectedId
                      ? 'conversation-item conversation-item--selected'
                      : 'conversation-item'
                  }
                  aria-current={
                    conversation.id === selectedId ? 'page' : undefined
                  }
                  onClick={() => {
                    setSelectedId(conversation.id)
                    setError(null)
                    setCanceled(false)
                    setOpenCitation(null)
                  }}
                >
                  <strong>{conversation.title}</strong>
                  <small>Updated {displayDate(conversation.updated_at)}</small>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="chat-panel" aria-labelledby="chat-panel-title">
          <div className="chat-panel__heading">
            <div>
              <p className="eyebrow">Secured conversation</p>
              <h2 id="chat-panel-title">
                {selectedConversation?.title ?? 'Ask from authorized evidence'}
              </h2>
            </div>
            <span className="status-badge status-badge--ready">
              Citation validation on
            </span>
          </div>

          <div className="suggested-questions">
            <p>Suggested questions</p>
            <div>
              {SUGGESTED_QUESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  disabled={sending}
                  onClick={() => setQuestion(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>

          <div className="chat-transcript" aria-live="polite">
            {turns.length === 0 ? (
              <div className="empty-state">
                {selectedConversation
                  ? 'This persisted conversation is ready for a new question. Earlier messages are not loaded by the Step 6 API.'
                  : 'Choose a suggestion or enter a question. A private conversation will be created automatically.'}
              </div>
            ) : (
              turns.map((turn) => (
                <div className="chat-turn" key={turn.id}>
                  <article className="question-card">
                    <p className="eyebrow">You</p>
                    <p>{turn.question}</p>
                  </article>
                  <GroundedAnswer
                    response={
                      turn.kind === 'agent'
                        ? agentAnswer(turn.response)
                        : turn.response
                    }
                    onOpenEvidence={setOpenCitation}
                  />
                  {turn.kind === 'agent'
                    ? turn.response.calculations.map((calculation) => (
                        <CalculationCard
                          key={calculation.calculation_id}
                          calculation={calculation}
                          citations={turn.response.citations}
                          onOpenEvidence={setOpenCitation}
                        />
                      ))
                    : null}
                  {turn.kind === 'agent' ? (
                    <AgentTraceTimeline
                      run={turn.response}
                      onOpenEvidence={setOpenCitation}
                    />
                  ) : null}
                </div>
              ))
            )}
            {sending ? (
              <section className="chat-loading-card" role="status">
                <span className="loading-dot" aria-hidden="true" />
                <div>
                  <strong>
                    {sendingMode === 'agent'
                      ? 'Running a bounded agent flow through approved tools…'
                      : 'Retrieving authorized evidence and validating citations…'}
                  </strong>
                  <small>
                    {sendingMode === 'agent'
                      ? 'The run stops at configured limits and exposes only a sanitized timeline.'
                      : 'Only a complete, validated response will be displayed.'}
                  </small>
                </div>
              </section>
            ) : null}
            {canceled ? (
              <section className="chat-state-card" role="status">
                <h3>Request canceled</h3>
                <p>
                  Generation was canceled in this browser. No partial answer is
                  displayed.
                </p>
              </section>
            ) : null}
            {error ? <ErrorCard error={error} /> : null}
            {pendingApproval ? (
              <AgentApprovalCard
                approval={pendingApproval.data.approval}
                resolving={approvalResolving}
                onApprove={() => void resolvePending('approve_once')}
                onReject={() => void resolvePending('reject')}
                onStop={() => void stopPending()}
                onChangeRequest={(content) => void submitChange(content)}
              />
            ) : null}
            {approvalStatus ? <p role="status">{approvalStatus}</p> : null}
            {upgradeRequest ? (
              <section
                className="chat-state-card chat-state-card--upgrade"
                role="alert"
              >
                <p className="eyebrow">Deep mode required</p>
                <h3>
                  This request needs Deep mode because it requires broader
                  analysis.
                </h3>
                <p>
                  No provider or agent-stage call was made for the Fast attempt.
                </p>
                <div className="upgrade-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={sending}
                    onClick={() => void continueWithDeep()}
                  >
                    Continue with Deep
                  </button>
                  <button
                    type="button"
                    disabled={sending}
                    onClick={() => setUpgradeRequest(null)}
                  >
                    Cancel
                  </button>
                </div>
              </section>
            ) : null}
          </div>

          <form
            className="chat-composer"
            aria-busy={sending}
            onSubmit={(event) => void submit(event)}
          >
            <fieldset className="response-mode-control" disabled={sending}>
              <legend>Response mode</legend>
              <div className="response-mode-options">
                {(
                  [
                    [
                      'fast',
                      'Fast',
                      'Lower cost. Best for simple questions from clear evidence.',
                    ],
                    [
                      'auto',
                      'Auto',
                      'Recommended. The system chooses the appropriate model.',
                    ],
                    [
                      'deep',
                      'Deep',
                      'Uses the stronger model for comparisons and complex analysis.',
                    ],
                  ] as const
                ).map(([value, label, description]) => (
                  <label key={value} className="response-mode-option">
                    <input
                      type="radio"
                      name="response-mode"
                      value={value}
                      checked={responseMode === value}
                      onChange={() => setResponseMode(value)}
                    />
                    <span>{label}</span>
                    <small>{description}</small>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset
              className="response-mode-control"
              disabled={sending || approvalResolving}
            >
              <legend>Agent control mode</legend>
              <p className="field-help">
                Response mode controls model capability. Agent control controls
                when tools pause.
              </p>
              <div className="response-mode-options">
                {(
                  [
                    ['guided', 'Guided', 'Pause before every tool action.'],
                    [
                      'balanced',
                      'Balanced',
                      'Run safe read-only tools; pause for higher risk.',
                    ],
                    [
                      'autonomous',
                      'Autonomous',
                      'Run authorized tools inside fixed host limits.',
                    ],
                  ] as const
                ).map(([value, label, description]) => (
                  <label key={value} className="response-mode-option">
                    <input
                      type="radio"
                      name="agent-control-mode"
                      value={value}
                      checked={agentControlMode === value}
                      onChange={() => setAgentControlMode(value)}
                    />
                    <span>{label}</span>
                    <small>{description}</small>
                  </label>
                ))}
              </div>
            </fieldset>
            <label htmlFor="chat-question">Ask about approved documents</label>
            <textarea
              id="chat-question"
              value={question}
              maxLength={CHAT_QUESTION_MAX_LENGTH}
              rows={4}
              disabled={sending}
              placeholder="Ask a question that can be supported by your authorized portfolio documents…"
              onChange={(event) => setQuestion(event.target.value)}
            />
            <div className="chat-composer__actions">
              <small>
                {question.length}/{CHAT_QUESTION_MAX_LENGTH} characters
              </small>
              {sending ? (
                <button type="button" onClick={cancelRequest}>
                  Cancel response
                </button>
              ) : null}
              <button
                type="submit"
                className="primary-button"
                name="submission-mode"
                value="grounded"
                disabled={sending || creating}
              >
                Ask copilot
              </button>
              <button
                type="submit"
                className="agent-button"
                name="submission-mode"
                value="agent"
                disabled={sending || creating}
              >
                Run bounded agent
              </button>
            </div>
          </form>
        </section>
      </div>

      <EvidenceDrawer citation={openCitation} onClose={closeEvidence} />
    </div>
  )
}
