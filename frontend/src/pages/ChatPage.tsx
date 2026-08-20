import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import {
  createConversation,
  listConversations,
  sendConversationMessage,
} from '../api/chat'
import { useAuth } from '../auth/useAuth'
import { EvidenceDrawer } from '../components/EvidenceDrawer'
import { GroundedAnswer } from '../components/GroundedAnswer'
import type {
  ChatTurn,
  ConversationData,
  GroundedCitationData,
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
])
const DENIAL_CODES = new Set([
  'forbidden',
  'authorization_denied',
  'conversation_not_found',
])

function safeError(error: unknown): SafeError {
  if (error instanceof ApiError) {
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

export function ChatPage() {
  const auth = useAuth()
  const [conversations, setConversations] = useState<ConversationData[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [turnsByConversation, setTurnsByConversation] = useState<
    Record<string, ChatTurn[]>
  >({})
  const [question, setQuestion] = useState('')
  const [loadingList, setLoadingList] = useState(true)
  const [creating, setCreating] = useState(false)
  const [sending, setSending] = useState(false)
  const [canceled, setCanceled] = useState(false)
  const [error, setError] = useState<SafeError | null>(null)
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
    setError(null)
    setCanceled(false)
    setOpenCitation(null)
    try {
      let conversationId = selectedId
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
      const response = await sendConversationMessage(
        auth.accessToken,
        conversationId,
        content,
        controller.signal,
      )
      const turn: ChatTurn = {
        id: response.data.assistant_message_id,
        question: content,
        response: response.data,
      }
      setTurnsByConversation((current) => ({
        ...current,
        [conversationId]: [...(current[conversationId] ?? []), turn],
      }))
      setQuestion('')
    } catch (requestError) {
      if (
        requestError instanceof DOMException &&
        requestError.name === 'AbortError'
      ) {
        setCanceled(true)
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
                    response={turn.response}
                    onOpenEvidence={setOpenCitation}
                  />
                </div>
              ))
            )}
            {sending ? (
              <section className="chat-loading-card" role="status">
                <span className="loading-dot" aria-hidden="true" />
                <div>
                  <strong>
                    Retrieving authorized evidence and validating citations…
                  </strong>
                  <small>
                    Only a complete, validated response will be displayed.
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
          </div>

          <form
            className="chat-composer"
            aria-busy={sending}
            onSubmit={(event) => void submit(event)}
          >
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
                disabled={sending || creating}
              >
                Ask copilot
              </button>
            </div>
          </form>
        </section>
      </div>

      <EvidenceDrawer citation={openCitation} onClose={closeEvidence} />
    </div>
  )
}
