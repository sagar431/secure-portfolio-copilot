import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/context'
import { EvaluationDashboardPage } from './EvaluationDashboardPage'
import type {
  EvaluationCategory,
  EvaluationRunDetail,
  SafeCaseResult,
} from '../types/evaluations'

const api = vi.hoisted(() => ({
  listEvaluations: vi.fn(),
  getEvaluation: vi.fn(),
  runEvaluation: vi.fn(),
  downloadEvaluationReport: vi.fn(),
}))

vi.mock('../api/evaluations', () => api)

const categoryCounts: Array<[EvaluationCategory, number]> = [
  ['authorized_positive', 20],
  ['explicit_denial', 10],
  ['memory_isolation', 4],
  ['deterministic_calculation', 4],
  ['insufficient_evidence', 4],
]

function results(): SafeCaseResult[] {
  let sequence = 0
  return categoryCounts.flatMap(([category, count]) =>
    Array.from({ length: count }, () => {
      sequence += 1
      return {
        case_id: `EV-${String(sequence).padStart(3, '0')}`,
        category,
        status: 'PASS',
        reason_code: 'SAFE_REASON_CODE',
        expected_identifiers: ['SAFE-DOC-ID'],
        actual_identifiers: ['SAFE-DOC-ID'],
        metrics: { citation_present: true },
        duration_ms: 12,
        model_route: 'authorized_search',
        model_name: null,
        input_tokens: null,
        output_tokens: null,
        cost_usd: null,
        retry_count: 0,
        fallback_used: false,
        fallback_reason_code: null,
        started_at: '2026-08-21T00:00:00Z',
        completed_at: '2026-08-21T00:00:00Z',
      }
    }),
  )
}

function run(
  status: EvaluationRunDetail['status'] = 'PASSED',
): EvaluationRunDetail {
  const gates = [
    'cross_tenant_denial',
    'cross_department_denial',
    'memory_isolation',
    'calculation_exactness',
    'citation_presence',
    'retrieval_recall_at_5',
    'citation_support_precision',
    'abstention_correctness',
  ].map((name) => ({ name, value: 1, threshold: 0.9, passed: true }))
  return {
    id: 'run-id',
    status,
    manifest_version: '1.0.0',
    manifest_hash: 'a'.repeat(64),
    advisory_judge_enabled: true,
    advisory_judge_label: 'ADVISORY_ONLY',
    metrics: {
      total: 42,
      passed: 42,
      failed: 0,
      errors: 0,
      cross_tenant_deny_pass_rate: 1,
      cross_department_deny_pass_rate: 1,
      memory_isolation_pass_rate: 1,
      calculation_exactness: 1,
      retrieval_recall_at_5: 1,
      citation_presence_rate: 1,
      citation_support_precision: 1,
      abstention_correctness: 1,
      average_latency_ms: 12,
      p95_latency_ms: 20,
      input_tokens: 10,
      output_tokens: 5,
      provider_cost_usd: 0.001,
      estimated_cost_usd: 0.001,
      model_route_distribution: { authorized_search: 20 },
      fallback_count: 0,
      retry_count: 0,
    },
    release_gates: gates,
    started_at: '2026-08-21T00:00:00Z',
    completed_at: '2026-08-21T00:01:00Z',
    created_at: '2026-08-21T00:00:00Z',
    results: results(),
  }
}

const auth: AuthContextValue = {
  status: 'authenticated',
  currentUser: null,
  accessToken: 'admin-token',
  login: vi.fn(),
  logout: vi.fn(),
}

function renderPage() {
  return render(
    <AuthContext.Provider value={auth}>
      <EvaluationDashboardPage />
    </AuthContext.Provider>,
  )
}

describe('EvaluationDashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty and running states and starts with the judge off', async () => {
    api.listEvaluations.mockResolvedValue({ data: { runs: [] } })
    let finish: ((value: object) => void) | undefined
    api.runEvaluation.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    renderPage()

    expect(
      await screen.findByText('No evaluation runs yet'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run evaluation' }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'Evaluation is running',
    )
    expect(api.runEvaluation).toHaveBeenCalledWith('admin-token', false)
    finish?.({ data: run() })
    expect(await screen.findByText('PASSED')).toBeInTheDocument()
  })

  it('renders aggregate metrics, exact composition, safe results, filters, and download', async () => {
    const detail = run()
    api.listEvaluations.mockResolvedValue({ data: { runs: [detail] } })
    api.getEvaluation.mockResolvedValue({ data: detail })
    api.downloadEvaluationReport.mockResolvedValue(undefined)
    renderPage()

    expect(await screen.findByText('Retrieval Recall@5')).toBeInTheDocument()
    expect(screen.getByText('Judge: ADVISORY ONLY')).toBeInTheDocument()
    expect(screen.getAllByText('20').length).toBeGreaterThan(0)
    expect(screen.getAllByText('10').length).toBeGreaterThan(0)
    expect(screen.getAllByText('4').length).toBeGreaterThan(0)
    expect(
      screen.queryByText(/What was|question|excerpt/i),
    ).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'memory_isolation' },
    })
    expect(screen.getByText('EV-031')).toBeInTheDocument()
    expect(screen.getByText('EV-034')).toBeInTheDocument()
    expect(screen.queryByText('EV-001')).not.toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Download JSON report' }),
    )
    await waitFor(() =>
      expect(api.downloadEvaluationReport).toHaveBeenCalledWith(
        'admin-token',
        'run-id',
      ),
    )
  })

  it('presents SECURITY_FAILED prominently and shows safe API failures', async () => {
    const detail = run('SECURITY_FAILED')
    api.listEvaluations.mockResolvedValue({ data: { runs: [detail] } })
    api.getEvaluation.mockResolvedValue({ data: detail })
    renderPage()

    expect(await screen.findByText('SECURITY_FAILED')).toBeInTheDocument()
    expect(
      screen.getByText(/Authorization leakage was confirmed/),
    ).toBeInTheDocument()

    api.runEvaluation.mockRejectedValue(new Error('provider raw secret'))
    fireEvent.click(screen.getByRole('button', { name: 'Run evaluation' }))
    expect(
      await screen.findByText('The evaluation run failed safely.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('provider raw secret')).not.toBeInTheDocument()
  })
})
