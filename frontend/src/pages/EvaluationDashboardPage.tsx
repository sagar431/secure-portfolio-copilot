import { useEffect, useMemo, useState } from 'react'

import {
  downloadEvaluationReport,
  getEvaluation,
  listEvaluations,
  runEvaluation,
} from '../api/evaluations'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import type {
  EvaluationCategory,
  EvaluationRunDetail,
} from '../types/evaluations'

const categories: EvaluationCategory[] = [
  'authorized_positive',
  'explicit_denial',
  'memory_isolation',
  'deterministic_calculation',
  'insufficient_evidence',
]

const metricCards: Array<
  [string, keyof NonNullable<EvaluationRunDetail['metrics']>, 'rate' | 'number']
> = [
  ['Cross-tenant denial', 'cross_tenant_deny_pass_rate', 'rate'],
  ['Cross-department denial', 'cross_department_deny_pass_rate', 'rate'],
  ['Memory isolation', 'memory_isolation_pass_rate', 'rate'],
  ['Calculation exactness', 'calculation_exactness', 'rate'],
  ['Retrieval Recall@5', 'retrieval_recall_at_5', 'rate'],
  ['Citation presence', 'citation_presence_rate', 'rate'],
  ['Citation support precision', 'citation_support_precision', 'rate'],
  ['Abstention correctness', 'abstention_correctness', 'rate'],
  ['Average latency', 'average_latency_ms', 'number'],
  ['P95 latency', 'p95_latency_ms', 'number'],
]

function label(value: string) {
  return value.replaceAll('_', ' ')
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

export function EvaluationDashboardPage() {
  const { accessToken } = useAuth()
  const [run, setRun] = useState<EvaluationRunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [judge, setJudge] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<
    'all' | EvaluationCategory
  >('all')
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'PASS' | 'FAIL' | 'ERROR'
  >('all')

  useEffect(() => {
    if (!accessToken) return
    const controller = new AbortController()
    async function load() {
      try {
        const listing = await listEvaluations(
          accessToken as string,
          controller.signal,
        )
        const latest = listing.data.runs[0]
        if (latest) {
          const detail = await getEvaluation(
            accessToken as string,
            latest.id,
            controller.signal,
          )
          setRun(detail.data)
        }
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(
            caught instanceof ApiError
              ? caught.message
              : 'Evaluation history could not be loaded.',
          )
        }
      } finally {
        setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [accessToken])

  const filteredResults = useMemo(
    () =>
      (run?.results ?? []).filter(
        (item) =>
          (categoryFilter === 'all' || item.category === categoryFilter) &&
          (statusFilter === 'all' || item.status === statusFilter),
      ),
    [run, categoryFilter, statusFilter],
  )

  const categoryCounts = useMemo(
    () =>
      Object.fromEntries(
        categories.map((category) => [
          category,
          (run?.results ?? []).filter((item) => item.category === category)
            .length,
        ]),
      ),
    [run],
  )

  async function startRun() {
    if (!accessToken || running) return
    setRunning(true)
    setError(null)
    try {
      const response = await runEvaluation(accessToken, judge)
      setRun(response.data)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'The evaluation run failed safely.',
      )
    } finally {
      setRunning(false)
    }
  }

  async function download() {
    if (!accessToken || !run) return
    try {
      await downloadEvaluationReport(accessToken, run.id)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'The report could not be downloaded.',
      )
    }
  }

  return (
    <section className="evaluation-page" aria-labelledby="evaluation-title">
      <div className="page-heading-row">
        <div>
          <p className="eyebrow">Platform administration</p>
          <h1 id="evaluation-title">Secure evaluation</h1>
          <p>
            Run the fixed 42-case release suite. Result details contain safe
            identifiers and reason codes only.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void startRun()}
          disabled={running}
        >
          {running ? 'Running 42 cases…' : 'Run evaluation'}
        </button>
      </div>

      <div className="judge-control">
        <label>
          <input
            type="checkbox"
            checked={judge}
            onChange={(event) => setJudge(event.target.checked)}
            disabled={running}
          />
          Use optional Gemini faithfulness judge
        </label>
        <p>
          Advisory only. At most two authorized, grounded cases are sent through
          Google Vertex BYOK; deterministic security gates always override it.
        </p>
      </div>

      {error ? <div className="status-banner error-banner">{error}</div> : null}
      {running ? (
        <div className="status-banner" role="status">
          Evaluation is running. Duplicate runs are blocked until completion.
        </div>
      ) : null}
      {loading ? <p role="status">Loading evaluation history…</p> : null}
      {!loading && !run ? (
        <div className="empty-state">
          <h2>No evaluation runs yet</h2>
          <p>
            Run the versioned deterministic suite to establish release
            readiness.
          </p>
        </div>
      ) : null}

      {run ? (
        <>
          <section
            className={`evaluation-summary status-${run.status.toLowerCase()}`}
            aria-label="Evaluation release summary"
          >
            <div>
              <p className="eyebrow">Release status</p>
              <h2>{run.status}</h2>
              {run.status === 'SECURITY_FAILED' ? (
                <p className="security-warning">
                  Authorization leakage was confirmed. This run is blocked
                  regardless of all other scores.
                </p>
              ) : null}
            </div>
            <div className="run-meta">
              <span>Suite {run.manifest_version}</span>
              <span>Manifest {run.manifest_hash.slice(0, 12)}…</span>
              {run.advisory_judge_enabled ? (
                <span className="advisory-badge">Judge: ADVISORY ONLY</span>
              ) : null}
              <button type="button" onClick={() => void download()}>
                Download JSON report
              </button>
            </div>
          </section>

          <section aria-labelledby="gate-title">
            <h2 id="gate-title">Release gates</h2>
            <div className="gate-grid">
              {run.release_gates.map((gate) => (
                <article
                  className={gate.passed ? 'gate-pass' : 'gate-fail'}
                  key={gate.name}
                >
                  <span>{label(gate.name)}</span>
                  <strong>{percent(gate.value)}</strong>
                  <small>
                    threshold {percent(gate.threshold)} ·{' '}
                    {gate.passed ? 'Pass' : 'Fail'}
                  </small>
                </article>
              ))}
            </div>
          </section>

          <section aria-labelledby="composition-title">
            <h2 id="composition-title">Case composition</h2>
            <div className="category-counts">
              {categories.map((category) => (
                <div key={category}>
                  <strong>{categoryCounts[category]}</strong>
                  <span>{label(category)}</span>
                </div>
              ))}
            </div>
          </section>

          {run.metrics ? (
            <>
              <section aria-labelledby="metrics-title">
                <h2 id="metrics-title">Security and quality metrics</h2>
                <div className="metric-grid">
                  {metricCards.map(([name, key, kind]) => (
                    <article key={key}>
                      <span>{name}</span>
                      <strong>
                        {kind === 'rate'
                          ? percent(run.metrics?.[key] as number)
                          : `${(run.metrics?.[key] as number).toFixed(1)} ms`}
                      </strong>
                    </article>
                  ))}
                </div>
              </section>

              <section
                className="operations-grid"
                aria-label="Model routing cost and latency"
              >
                <article>
                  <h2>Outcome</h2>
                  <p>
                    {run.metrics.passed} passed · {run.metrics.failed} failed ·{' '}
                    {run.metrics.errors} errors
                  </p>
                  <p>
                    Tokens {run.metrics.input_tokens} in /{' '}
                    {run.metrics.output_tokens} out
                  </p>
                </article>
                <article>
                  <h2>Routing</h2>
                  {Object.entries(run.metrics.model_route_distribution).map(
                    ([route, count]) => (
                      <p key={route}>
                        {route}: {count}
                      </p>
                    ),
                  )}
                  {!Object.keys(run.metrics.model_route_distribution).length ? (
                    <p>No model routes recorded.</p>
                  ) : null}
                </article>
                <article>
                  <h2>Provider use</h2>
                  <p>Cost ${run.metrics.provider_cost_usd.toFixed(6)}</p>
                  <p>
                    {run.metrics.fallback_count} fallbacks ·{' '}
                    {run.metrics.retry_count} retries
                  </p>
                </article>
              </section>
            </>
          ) : null}

          <section aria-labelledby="results-title">
            <div className="result-heading-row">
              <h2 id="results-title">Safe case results</h2>
              <div className="result-filters">
                <label>
                  Category
                  <select
                    value={categoryFilter}
                    onChange={(event) =>
                      setCategoryFilter(
                        event.target.value as typeof categoryFilter,
                      )
                    }
                  >
                    <option value="all">All</option>
                    {categories.map((category) => (
                      <option key={category} value={category}>
                        {label(category)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Status
                  <select
                    value={statusFilter}
                    onChange={(event) =>
                      setStatusFilter(event.target.value as typeof statusFilter)
                    }
                  >
                    <option value="all">All</option>
                    <option value="PASS">Pass</option>
                    <option value="FAIL">Fail</option>
                    <option value="ERROR">Error</option>
                  </select>
                </label>
              </div>
            </div>
            <div className="table-scroll">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Safe details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredResults.map((result) => (
                    <tr key={result.case_id}>
                      <td>{result.case_id}</td>
                      <td>{label(result.category)}</td>
                      <td>
                        <span
                          className={`case-status case-${result.status.toLowerCase()}`}
                        >
                          {result.status}
                        </span>
                      </td>
                      <td>{result.duration_ms} ms</td>
                      <td>
                        <details>
                          <summary>{result.reason_code}</summary>
                          <dl className="safe-identifiers">
                            <dt>Expected identifiers</dt>
                            <dd>
                              {result.expected_identifiers.join(', ') || 'None'}
                            </dd>
                            <dt>Actual identifiers</dt>
                            <dd>
                              {result.actual_identifiers.join(', ') || 'None'}
                            </dd>
                            <dt>Route</dt>
                            <dd>{result.model_route ?? 'No model route'}</dd>
                          </dl>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </section>
  )
}
