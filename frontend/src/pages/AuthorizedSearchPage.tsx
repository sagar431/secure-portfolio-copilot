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
  const { source } = result
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
        <p className="search-score">
          <span>Score</span>
          <strong>{result.score.toFixed(4)}</strong>
        </p>
      </div>
      <p className="search-excerpt">{result.excerpt}</p>
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
      <div className="search-source">
        <h4>Source provenance</h4>
        <Provenance result={result} />
      </div>
    </article>
  )
}

function SearchOutcome({ data }: { data: AuthorizedSearchData }) {
  const isIndexing =
    data.status === 'indexing' || data.indexing.status === 'indexing'
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
        </div>
      </div>
      {isIndexing ? (
        <div className="indexing-state" role="status">
          Indexing is still in progress. Results include only chunks currently
          active and authorized by the server.
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
            authorization scope. The browser renders the server response as-is
            and does not filter candidate documents.
          </p>
        </div>
        <aside className="security-note">
          <strong>Backend-enforced boundary</strong>
          <span>
            Tenant, company, department, visibility, approval, deletion, and
            active-version checks run before results leave the repository.
          </span>
        </aside>
      </header>

      {auth.currentUser ? (
        <AuthorizationScopePanel user={auth.currentUser} />
      ) : null}

      <section className="search-card" aria-labelledby="search-form-title">
        <div>
          <p className="eyebrow">Deterministic keyword retrieval</p>
          <h2 id="search-form-title">Search approved documents</h2>
        </div>
        <form className="search-form" onSubmit={(event) => void submit(event)}>
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
          <div className="search-loading" role="status">
            Searching the authorized index…
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
