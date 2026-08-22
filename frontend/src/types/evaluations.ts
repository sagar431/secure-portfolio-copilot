export type EvaluationCategory =
  | 'authorized_positive'
  | 'explicit_denial'
  | 'memory_isolation'
  | 'deterministic_calculation'
  | 'insufficient_evidence'

export type EvaluationRunStatus =
  'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED' | 'SECURITY_FAILED' | 'ERROR'

export type EvaluationCaseStatus = 'PASS' | 'FAIL' | 'ERROR'

export interface EvaluationMetrics {
  total: number
  passed: number
  failed: number
  errors: number
  cross_tenant_deny_pass_rate: number
  cross_department_deny_pass_rate: number
  memory_isolation_pass_rate: number
  calculation_exactness: number
  retrieval_recall_at_5: number
  citation_presence_rate: number
  citation_support_precision: number
  abstention_correctness: number
  average_latency_ms: number
  p95_latency_ms: number
  input_tokens: number
  output_tokens: number
  provider_cost_usd: number
  estimated_cost_usd: number
  model_route_distribution: Record<string, number>
  fallback_count: number
  retry_count: number
}

export interface ReleaseGate {
  name: string
  value: number
  threshold: number
  passed: boolean
}

export interface SafeCaseResult {
  case_id: string
  category: EvaluationCategory
  status: EvaluationCaseStatus
  reason_code: string
  expected_identifiers: string[]
  actual_identifiers: string[]
  metrics: Record<string, number | boolean | string | null>
  duration_ms: number
  model_route: string | null
  model_name: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  retry_count: number
  fallback_used: boolean
  fallback_reason_code: string | null
  started_at: string
  completed_at: string
}

export interface EvaluationRunSummary {
  id: string
  status: EvaluationRunStatus
  manifest_version: string
  manifest_hash: string
  advisory_judge_enabled: boolean
  advisory_judge_label: 'ADVISORY_ONLY'
  metrics: EvaluationMetrics | null
  release_gates: ReleaseGate[]
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  results: SafeCaseResult[]
}

export interface EvaluationRunList {
  runs: EvaluationRunSummary[]
}
