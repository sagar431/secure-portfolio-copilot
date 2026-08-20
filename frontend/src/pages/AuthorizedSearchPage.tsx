import { useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import { searchAuthorizedDocuments } from '../api/search'
import { useAuth } from '../auth/useAuth'
import { AuthorizationScopePanel } from '../components/AuthorizationScopePanel'
import type {
  AuthorizedSearchData,
  AuthorizedSearchResultData,
} from '../types/search'
import {
  SEARCH_QUERY_MAX_LENGTH,
  SEARCH_TOP_K_DEFAULT,
  SEARCH_TOP_K_MAX,
  SEARCH_TOP_K_MIN,
} from '../types/search'

function label(value: string) {
  return value.replaceAll('-', ' ').replaceAll('_', ' ')
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    const requestId = error.requestId ? ` Request ID: ${error.requestId}` : ''
    return `${error.message}${requestId}`
  }
  return 'Authorized search could not be completed. Try again.'
}

function Provenance({ result }: { result: AuthorizedSearchResultData }) {
  const source = result.citation
  return (
    <dl className="search-provenance">
      <div>
        <dt>Page</dt>
        <dd>{source.page_number ?? '—'}</dd>
      </div>
      <div>
        <dt>Sheet</dt>
        <dd>{source.sheet_name ?? '—'}</dd>
      </div>
      <div>
        <dt>Rows</dt>
        <dd>
          {source.row_start === null
            ? '—'
            : source.row_end === source.row_start || source.row_end === null
              ? source.row_start
              : `${source.row_start}–${source.row_end}`}
        </dd>
      </div>
      <div>
        <dt>Cells</dt>
        <dd>
          {source.cell_start === null
            ? '—'
            : source.cell_end === source.cell_start || source.cell_end === null
              ? source.cell_start
              : `${source.cell_start}–${source.cell_end}`}
        </dd>
      </div>
    </dl>
  )
}

function ScoreBreakdown({ result }: { result: AuthorizedSearchResultData }) {
  return (
    <dl className="search-scores" aria-label="Deterministic hybrid scores">
      <div>
        <dt>Keyword</dt>
        <dd>{result.scores.keyword.toFixed(4)}</dd>
      </div>
      <div>
        <dt>Vector</dt>
        <dd>{result.scores.vector.toFixed(4)}</dd>
      </div>
      <div className="search-score-final">
        <dt>Final</dt>
        <dd>{result.scores.final.toFixed(4)}</dd>
      </div>
    </dl>
  )
}

function CitationPreview({ result }: { result: AuthorizedSearchResultData }) {
  const { citation } = result
  return (
    <section className="citation-preview" aria-label="Citation preview">
      <div className="citation-heading">
        <div>
          <p className="eyebrow">Citation preview</p>
          <h4>{citation.document_title}</h4>
        </div>
        <span className="status-badge">Version {citation.version_number}</span>
      </div>
      <p className="search-excerpt">{citation.excerpt}</p>
      <dl className="search-identifiers">
        <div>
          <dt>Citation chunk ID</dt>
          <dd>{citation.chunk_id}</dd>
        </div>
        <div>
          <dt>Citation document ID</dt>
          <dd>{citation.document_id}</dd>
        </div>
        <div>
          <dt>Citation version ID</dt>
          <dd>{citation.document_version_id}</dd>
        </div>
      </dl>
      <Provenance result={result} />
    </section>
  )
}

function SearchResult({
  result,
  position,
}: {
  result: AuthorizedSearchResultData
  position: number
}) {
  return (
    <article className="search-result">
      <div className="search-result-heading">
        <div>
          <p className="eyebrow">Result {position}</p>
          <h3>{result.document.filename}</h3>
        </div>
        <ScoreBreakdown result={result} />
      </div>
      <dl className="search-identifiers">
        <div>
          <dt>Chunk ID</dt>
          <dd>{result.chunk_id}</dd>
        </div>
        <div>
          <dt>Document ID</dt>
          <dd>{result.document_id}</dd>
        </div>
        <div>
          <dt>Version ID</dt>
          <dd>{result.document_version_id}</dd>
        </div>
        <div>
          <dt>Version</dt>
          <dd>{result.version_number}</dd>
        </div>
      </dl>
      <dl className="search-metadata">
        <div>
          <dt>Source</dt>
          <dd>{result.document.source_type}</dd>
        </div>
        <div>
          <dt>Document type</dt>
          <dd>{label(result.document.document_type)}</dd>
        </div>
        <div>
          <dt>Tenant</dt>
          <dd>{result.document.tenant_slug}</dd>
        </div>
        <div>
          <dt>Company</dt>
          <dd>{result.document.company_slug}</dd>
        </div>
        <div>
          <dt>Department</dt>
          <dd>{label(result.document.department)}</dd>
        </div>
        <div>
          <dt>Visibility</dt>
          <dd>{label(result.document.visibility)}</dd>
        </div>
        <div>
          <dt>Classification</dt>
          <dd>{label(result.document.classification)}</dd>
        </div>
        <div>
          <dt>Reporting period</dt>
          <dd>{result.document.reporting_period ?? 'Not specified'}</dd>
        </div>
      </dl>
      <CitationPreview result={result} />
    </article>
  )
}

function EvaluationSummary({ data }: { data: AuthorizedSearchData }) {
  const summary = data.evaluation_summary
  if (summary.status === 'not_run') {
    return (
      <aside className="evaluation-summary evaluation-summary--not-run">
        <div>
          <p className="eyebrow">Curated retrieval evaluation</p>
          <h3>Not run</h3>
        </div>
        <p>
          No aggregate evaluation is available. Search results remain scoped to
          this authenticated request.
        </p>
      </aside>
    )
  }
  return (
    <aside className="evaluation-summary">
      <div className="evaluation-heading">
        <div>
          <p className="eyebrow">Curated retrieval evaluation</p>
          <h3>{summary.dataset_name}</h3>
        </div>
        <span
          className={`status-badge ${
            summary.authorization_leak_count === 0
              ? 'status-badge--ready'
              : 'status-badge--degraded'
          }`}
        >
          {summary.authorization_leak_count === 0
            ? 'No authorization leaks'
            : 'Authorization check failed'}
        </span>
      </div>
      <dl className="evaluation-metrics">
        <div>
          <dt>Recall@5</dt>
          <dd>{(summary.recall_at_5 * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>Curated queries</dt>
          <dd>{summary.curated_query_count}</dd>
        </div>
        <div>
          <dt>Expected top-5 hits</dt>
          <dd>{summary.expected_top_5_hits}</dd>
        </div>
        <div>
          <dt>Authorization leaks</dt>
          <dd>{summary.authorization_leak_count}</dd>
        </div>
      </dl>
    </aside>
  )
}

function SearchOutcome({ data }: { data: AuthorizedSearchData }) {
  const isIndexing =
    data.status === 'indexing' ||
    data.indexing.status === 'indexing' ||
    data.indexing.embedding.status === 'indexing'
  const isDegraded =
    data.status === 'degraded' ||
    data.indexing.status === 'degraded' ||
    data.indexing.embedding.status === 'degraded' ||
    data.indexing.embedding.status === 'unavailable'
  return (
    <section className="search-results" aria-labelledby="search-results-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Server-authorized response</p>
          <h2 id="search-results-title">
            {data.result_count} {data.result_count === 1 ? 'result' : 'results'}
          </h2>
          <p className="search-query-summary">
            Query: <strong>{data.query}</strong> · top {data.top_k}
          </p>
        </div>
        <div className="index-summary" aria-label="Index status">
          <span
            className={`status-badge status-badge--${data.indexing.status}`}
          >
            {data.indexing.status}
          </span>
          <small>
            {data.indexing.active_chunk_count} active chunks across{' '}
            {data.indexing.indexed_document_count} documents
          </small>
          <span
            className={`status-badge status-badge--${data.indexing.embedding.status}`}
          >
            Embeddings {data.indexing.embedding.status}
          </span>
          <small>
            {data.indexing.embedding.embedded_chunk_count} embedded ·{' '}
            {data.indexing.embedding.pending_chunk_count} pending ·{' '}
            {data.indexing.embedding.failed_chunk_count} failed
          </small>
          <small>
            {data.indexing.embedding.model} ·{' '}
            {data.indexing.embedding.dimensions} dimensions
          </small>
        </div>
      </div>
      {isIndexing ? (
        <div className="indexing-state" role="status">
          Indexing is still in progress. Results include only chunks currently
          active and authorized by the server.
        </div>
      ) : null}
      {isDegraded ? (
        <div className="degraded-state" role="status">
          Hybrid retrieval is temporarily degraded. Only the safe, authorized
          results returned by the server are shown.
        </div>
      ) : null}
      {data.results.length === 0 ? (
        <div className="empty-state">
          No authorized results matched this query. Documents outside your
          server-derived scope are never sent to this page.
        </div>
      ) : (
        <div className="search-result-list">
          {data.results.map((result, index) => (
            <SearchResult
              key={result.chunk_id}
              result={result}
              position={index + 1}
            />
          ))}
        </div>
      )}
      <EvaluationSummary data={data} />
    </section>
  )
}

export function AuthorizedSearchPage() {
  const auth = useAuth()
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(SEARCH_TOP_K_DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<AuthorizedSearchData | null>(null)
  const activeRequest = useRef<AbortController | null>(null)

  useEffect(
    () => () => {
      activeRequest.current?.abort()
      activeRequest.current = null
    },
    [],
  )

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) {
      setOutcome(null)
      setError('Enter a search query.')
      return
    }
    if (!auth.accessToken) {
      setOutcome(null)
      setError('Your authenticated session is unavailable. Sign in again.')
      return
    }

    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    setLoading(true)
    setError(null)
    setOutcome(null)
    try {
      const response = await searchAuthorizedDocuments(
        auth.accessToken,
        { query: trimmedQuery, top_k: topK },
        controller.signal,
      )
      setOutcome(response.data)
    } catch (requestError) {
      if (
        requestError instanceof DOMException &&
        requestError.name === 'AbortError'
      ) {
        return
      }
      setError(errorMessage(requestError))
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
        setLoading(false)
      }
    }
  }

  return (
    <div className="search-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Development-only retrieval inspection</p>
          <h1>Authorized document search</h1>
          <p className="hero-copy">
            Search only approved, active chunks inside your server-derived
            authorization scope. Inspect deterministic keyword, vector, and
            final scores with citation provenance. The browser renders the
            server response as-is and does not filter candidate documents.
          </p>
        </div>
        <aside className="security-note">
          <strong>Backend-enforced boundary</strong>
          <span>
            Tenant, company, department, visibility, approval, deletion, and
            active-version checks run before vector ranking or top-k selection.
          </span>
        </aside>
      </header>

      {auth.currentUser ? (
        <AuthorizationScopePanel user={auth.currentUser} />
      ) : null}

      <section className="search-card" aria-labelledby="search-form-title">
        <div>
          <p className="eyebrow">Deterministic hybrid retrieval</p>
          <h2 id="search-form-title">Search approved documents</h2>
        </div>
        <form
          className="search-form"
          aria-busy={loading}
          onSubmit={(event) => void submit(event)}
        >
          <label>
            Query
            <input
              type="search"
              aria-label="Query"
              required
              maxLength={SEARCH_QUERY_MAX_LENGTH}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Enter a keyword or phrase"
              disabled={loading}
            />
            <small>
              {query.length}/{SEARCH_QUERY_MAX_LENGTH} characters
            </small>
          </label>
          <label>
            Top results
            <input
              type="number"
              aria-label="Top results"
              required
              min={SEARCH_TOP_K_MIN}
              max={SEARCH_TOP_K_MAX}
              step="1"
              value={topK}
              onChange={(event) => {
                const nextTopK = event.currentTarget.valueAsNumber
                if (Number.isInteger(nextTopK)) {
                  setTopK(nextTopK)
                }
              }}
              disabled={loading}
            />
            <small>
              Between {SEARCH_TOP_K_MIN} and {SEARCH_TOP_K_MAX}
            </small>
          </label>
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? 'Searching…' : 'Search authorized documents'}
          </button>
        </form>
        {loading ? (
          <div className="search-loading" role="status" aria-live="polite">
            Searching the authorized hybrid index…
          </div>
        ) : null}
        {error ? (
          <div role="alert" className="warning-panel">
            {error}
          </div>
        ) : null}
      </section>

      {outcome ? <SearchOutcome data={outcome} /> : null}
    </div>
  )
}
