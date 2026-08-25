import { useEffect, useMemo, useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import {
  createPrivateMemory,
  confirmMemory,
  deleteMemory,
  dismissMemory,
  inspectMemories,
} from '../api/memory'
import { useAuth } from '../auth/useAuth'
import type { MemoryData } from '../types/memory'

interface CompanyOption {
  id: string
  label: string
}

function messageFor(error: unknown) {
  return error instanceof ApiError ? error.message : 'Memory request failed.'
}

export function MemoryPage() {
  const auth = useAuth()
  const token = auth.accessToken
  const companies = useMemo(() => {
    const byId = new Map<string, CompanyOption>()
    for (const grant of auth.currentUser?.authorization_scope.grants ?? []) {
      if (!grant.capabilities.includes('QUERY_DOCUMENTS')) continue
      grant.company_ids.forEach((id, index) => {
        byId.set(id, {
          id,
          label: `${grant.workspace.name} · ${grant.company_slugs[index] ?? id}`,
        })
      })
    }
    return [...byId.values()]
  }, [auth.currentUser])
  const [memories, setMemories] = useState<MemoryData[]>([])
  const [companyId, setCompanyId] = useState(companies[0]?.id ?? '')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!companyId && companies[0]) setCompanyId(companies[0].id)
  }, [companies, companyId])

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    setBusy(true)
    inspectMemories(token, controller.signal)
      .then((response) => setMemories(response.data.memories))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
          setError(messageFor(reason))
        }
      })
      .finally(() => setBusy(false))
    return () => controller.abort()
  }, [token])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!token || !companyId) return
    setBusy(true)
    setError(null)
    try {
      const response = await createPrivateMemory(token, {
        companyId,
        content,
        expiresInDays: 90,
      })
      setMemories((current) => [response.data, ...current])
      setContent('')
    } catch (reason) {
      setError(messageFor(reason))
    } finally {
      setBusy(false)
    }
  }

  async function remove(memory: MemoryData) {
    if (!token || !memory.can_delete) return
    setBusy(true)
    setError(null)
    try {
      await deleteMemory(token, memory.id)
      setMemories((current) => current.filter((item) => item.id !== memory.id))
    } catch (reason) {
      setError(messageFor(reason))
    } finally {
      setBusy(false)
    }
  }

  async function resolvePending(
    memory: MemoryData,
    action: 'confirm' | 'dismiss',
  ) {
    if (!token || !memory.can_confirm) return
    setBusy(true)
    setError(null)
    try {
      if (action === 'confirm') {
        const response = await confirmMemory(token, memory.id)
        setMemories((current) =>
          current.map((item) => (item.id === memory.id ? response.data : item)),
        )
      } else {
        await dismissMemory(token, memory.id)
        setMemories((current) =>
          current.filter((item) => item.id !== memory.id),
        )
      }
    } catch (reason) {
      setError(messageFor(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="memory-page" aria-labelledby="memory-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Server-scoped memory</p>
          <h1 id="memory-title">Memory inspector</h1>
          <p className="supporting-copy">
            Only memories visible to your current tenant, company, department,
            user, classification, and unexpired source grants appear here.
          </p>
        </div>
        <aside className="security-note">
          <strong>Authorization is rechecked on every read.</strong>
          <span>
            Saved text is context, never an instruction or a citation.
          </span>
        </aside>
      </div>

      <form
        className="memory-create-card"
        onSubmit={(event) => void submit(event)}
      >
        <h2>Save a private preference</h2>
        <label>
          Company
          <select
            value={companyId}
            onChange={(event) => setCompanyId(event.target.value)}
            disabled={busy}
          >
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Preference
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            minLength={1}
            maxLength={1000}
            required
            disabled={busy}
            placeholder="Example: Present financial values in INR crores."
          />
        </label>
        <div className="button-row">
          <button
            className="primary-button"
            type="submit"
            disabled={busy || !companyId || !content.trim()}
          >
            Save private memory
          </button>
          <small>Private to your user; expires after 90 days.</small>
        </div>
      </form>

      {error ? (
        <p className="degraded-state" role="alert">
          {error}
        </p>
      ) : null}

      <section
        className="memory-list-card"
        aria-labelledby="visible-memory-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Currently authorized</p>
            <h2 id="visible-memory-title">Visible memories</h2>
          </div>
          <strong>{memories.length} visible</strong>
        </div>
        {busy && memories.length === 0 ? <p>Loading memories…</p> : null}
        {!busy && memories.length === 0 ? (
          <p className="supporting-copy">No visible, unexpired memories.</p>
        ) : null}
        {(
          [
            [
              'SEMANTIC',
              'Semantic memories',
              'Stable preferences and confirmed user choices.',
            ],
            [
              'EPISODIC',
              'Episodic memories',
              'Safe run summaries whose document sources are reauthorized before reuse.',
            ],
            [
              'CONVERSATION_SUMMARY',
              'Working memory',
              'Bounded recent turns and rolling conversation summaries.',
            ],
          ] as const
        ).map(([type, title, description]) => (
          <section
            className="memory-type-section"
            key={type}
            aria-label={title}
          >
            <div className="section-heading">
              <div>
                <h3>{title}</h3>
                <p className="supporting-copy">{description}</p>
              </div>
              <strong>
                {memories.filter((item) => item.memory_type === type).length}
              </strong>
            </div>
            <div className="memory-list">
              {memories
                .filter((item) => item.memory_type === type)
                .map((memory) => (
                  <article className="memory-item" key={memory.id}>
                    <div className="memory-item-heading">
                      <span className="status-badge">
                        {memory.memory_type.replaceAll('_', ' ')} ·{' '}
                        {memory.status.replaceAll('_', ' ')}
                      </span>
                      <div className="button-row">
                        {memory.can_confirm ? (
                          <>
                            <button
                              className="text-button"
                              type="button"
                              onClick={() =>
                                void resolvePending(memory, 'confirm')
                              }
                              disabled={busy}
                            >
                              Confirm
                            </button>
                            <button
                              className="text-button"
                              type="button"
                              onClick={() =>
                                void resolvePending(memory, 'dismiss')
                              }
                              disabled={busy}
                            >
                              Dismiss
                            </button>
                          </>
                        ) : null}
                        {memory.can_delete ? (
                          <button
                            className="danger-text-button text-button"
                            type="button"
                            onClick={() => void remove(memory)}
                            disabled={busy}
                          >
                            Delete
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <p>{memory.content}</p>
                    <dl className="memory-metadata">
                      <div>
                        <dt>Owner</dt>
                        <dd>{memory.owner_display}</dd>
                      </div>
                      <div>
                        <dt>Scope</dt>
                        <dd>
                          {memory.tenant_display} · {memory.company_display} ·{' '}
                          {memory.scope.replaceAll('_', ' ')}
                        </dd>
                      </div>
                      <div>
                        <dt>Origin</dt>
                        <dd>{memory.origin.replaceAll('_', ' ')}</dd>
                      </div>
                      <div>
                        <dt>Created</dt>
                        <dd>
                          {new Date(memory.created_at).toLocaleDateString()}
                        </dd>
                      </div>
                      <div>
                        <dt>Department</dt>
                        <dd>{memory.department}</dd>
                      </div>
                      <div>
                        <dt>Classification</dt>
                        <dd>{memory.classification}</dd>
                      </div>
                      <div>
                        <dt>Sources</dt>
                        <dd>
                          {memory.sources.length
                            ? memory.sources
                                .map((source) => source.document_name)
                                .join(', ')
                            : 'Conversation'}
                        </dd>
                      </div>
                      <div>
                        <dt>Source conversation</dt>
                        <dd>
                          {memory.source_conversation ?? 'Not applicable'}
                        </dd>
                      </div>
                      <div>
                        <dt>Why remembered</dt>
                        <dd>{memory.reason}</dd>
                      </div>
                      <div>
                        <dt>Expires</dt>
                        <dd>
                          {new Date(memory.expires_at).toLocaleDateString()}
                        </dd>
                      </div>
                    </dl>
                  </article>
                ))}
            </div>
          </section>
        ))}
      </section>
    </section>
  )
}
