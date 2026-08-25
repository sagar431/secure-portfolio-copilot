import { ApiError, isRecord, requestJson } from './client'
import type {
  AgentObservationHistory,
  AgentRunHistoryDetail,
  AgentRunHistoryList,
  AgentRunHistorySummary,
  AgentStepHistory,
  AgentTimelineEventHistory,
} from '../types/agentHistory'

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const REASON = /^[A-Z][A-Z0-9_]{1,95}$/
const TOOL =
  /^portfolio\.(search_authorized_documents|get_document_excerpt|query_financial_metrics|search_memory|propose_memory|calculate_(ebitda_margin|revenue_growth|net_profit_margin|debt_to_equity|cash_runway|cagr))$/
const STATUSES = new Set([
  'CREATED',
  'RUNNING',
  'AWAITING_APPROVAL',
  'COMPLETED',
  'REFUSED',
  'CLARIFICATION_REQUIRED',
  'INSUFFICIENT_EVIDENCE',
  'LIMIT_REACHED',
  'FAILED',
  'CANCELLED',
])

function exactKeys(value: Record<string, unknown>, keys: string[]) {
  return (
    Object.keys(value).length === keys.length &&
    keys.every((key) => key in value)
  )
}

function boundedInteger(value: unknown, maximum: number) {
  return (
    Number.isInteger(value) && Number(value) >= 0 && Number(value) <= maximum
  )
}

function nullableString(value: unknown) {
  return value === null || typeof value === 'string'
}

function isSummary(value: unknown): value is AgentRunHistorySummary {
  if (!isRecord(value)) return false
  if (
    !exactKeys(value, [
      'id',
      'conversation_id',
      'response_mode',
      'agent_control_mode',
      'selected_model_tier',
      'selected_model_name',
      'status',
      'safe_reason_code',
      'step_count',
      'retry_count',
      'duration_ms',
      'created_at',
      'started_at',
      'completed_at',
    ])
  )
    return false
  return (
    typeof value.id === 'string' &&
    UUID.test(value.id) &&
    typeof value.conversation_id === 'string' &&
    UUID.test(value.conversation_id) &&
    ['fast', 'auto', 'deep'].includes(String(value.response_mode)) &&
    ['guided', 'balanced', 'autonomous'].includes(
      String(value.agent_control_mode),
    ) &&
    (value.selected_model_tier === null ||
      value.selected_model_tier === 'fast' ||
      value.selected_model_tier === 'deep') &&
    (value.selected_model_name === null ||
      value.selected_model_name === 'Gemini 3.1 Flash Lite' ||
      value.selected_model_name === 'Gemini 3.7 Flash') &&
    typeof value.status === 'string' &&
    STATUSES.has(value.status) &&
    typeof value.safe_reason_code === 'string' &&
    REASON.test(value.safe_reason_code) &&
    boundedInteger(value.step_count, 4) &&
    boundedInteger(value.retry_count, 4) &&
    boundedInteger(value.duration_ms, 120_000) &&
    typeof value.created_at === 'string' &&
    nullableString(value.started_at) &&
    nullableString(value.completed_at)
  )
}

function isObservation(value: unknown): value is AgentObservationHistory {
  if (!isRecord(value)) return false
  return (
    exactKeys(value, [
      'status',
      'safe_reason_code',
      'authorized_document_ids',
      'authorized_chunk_ids',
      'citation_ids',
      'evidence_count',
      'retry_count',
      'duration_ms',
    ]) &&
    ['SUCCESS', 'DENIED', 'TIMEOUT', 'ERROR'].includes(String(value.status)) &&
    typeof value.safe_reason_code === 'string' &&
    REASON.test(value.safe_reason_code) &&
    Array.isArray(value.authorized_document_ids) &&
    value.authorized_document_ids.length <= 8 &&
    value.authorized_document_ids.every(
      (item) => typeof item === 'string' && UUID.test(item),
    ) &&
    Array.isArray(value.authorized_chunk_ids) &&
    value.authorized_chunk_ids.length <= 8 &&
    value.authorized_chunk_ids.every(
      (item) => typeof item === 'string' && UUID.test(item),
    ) &&
    Array.isArray(value.citation_ids) &&
    value.citation_ids.length <= 8 &&
    value.citation_ids.every(
      (item) => typeof item === 'string' && /^ev_[1-9][0-9]*$/.test(item),
    ) &&
    boundedInteger(value.evidence_count, 8) &&
    boundedInteger(value.retry_count, 1) &&
    boundedInteger(value.duration_ms, 120_000)
  )
}

function isStep(value: unknown): value is AgentStepHistory {
  if (!isRecord(value)) return false
  return (
    exactKeys(value, [
      'step_number',
      'plan_version',
      'plan_step_index',
      'action_name',
      'tool_name',
      'status',
      'policy_decision',
      'safe_reason_code',
      'duration_ms',
      'observation',
    ]) &&
    boundedInteger(value.step_number, 4) &&
    Number(value.step_number) >= 1 &&
    boundedInteger(value.plan_version, 2) &&
    Number(value.plan_version) >= 1 &&
    boundedInteger(value.plan_step_index, 2) &&
    value.action_name === 'TOOL_CALL' &&
    typeof value.tool_name === 'string' &&
    TOOL.test(value.tool_name) &&
    ['COMPLETED', 'DENIED', 'TIMEOUT', 'FAILED'].includes(
      String(value.status),
    ) &&
    ['ALLOWED', 'DENIED'].includes(String(value.policy_decision)) &&
    typeof value.safe_reason_code === 'string' &&
    REASON.test(value.safe_reason_code) &&
    boundedInteger(value.duration_ms, 120_000) &&
    (value.observation === null || isObservation(value.observation))
  )
}

function isTimeline(value: unknown): value is AgentTimelineEventHistory {
  if (!isRecord(value)) return false
  return (
    exactKeys(value, [
      'sequence',
      'stage',
      'status',
      'safe_reason_code',
      'summary',
      'tool_name',
      'step_number',
      'duration_ms',
    ]) &&
    boundedInteger(value.sequence, 20) &&
    Number(value.sequence) >= 1 &&
    [
      'perception',
      'policy',
      'decision',
      'tool',
      'observation',
      'final',
    ].includes(String(value.stage)) &&
    typeof value.status === 'string' &&
    /^[A-Z][A-Z0-9_]{1,31}$/.test(value.status) &&
    typeof value.safe_reason_code === 'string' &&
    REASON.test(value.safe_reason_code) &&
    typeof value.summary === 'string' &&
    value.summary.length >= 1 &&
    value.summary.length <= 160 &&
    (value.tool_name === null ||
      (typeof value.tool_name === 'string' && TOOL.test(value.tool_name))) &&
    (value.step_number === null ||
      (boundedInteger(value.step_number, 4) &&
        Number(value.step_number) >= 1)) &&
    boundedInteger(value.duration_ms, 120_000)
  )
}

function isDetail(value: unknown): value is AgentRunHistoryDetail {
  if (!isRecord(value)) return false
  const summary = Object.fromEntries(
    Object.entries(value).filter(
      ([key]) =>
        ![
          'final_assistant_message_id',
          'input_tokens',
          'output_tokens',
          'perception_status',
          'perception_reason_code',
          'policy_decision',
          'policy_reason_code',
          'plan_versions',
          'steps',
          'timeline',
        ].includes(key),
    ),
  )
  return (
    isSummary(summary) &&
    nullableString(value.final_assistant_message_id) &&
    (value.final_assistant_message_id === null ||
      UUID.test(value.final_assistant_message_id)) &&
    (value.input_tokens === null ||
      boundedInteger(value.input_tokens, 1_000_000)) &&
    (value.output_tokens === null ||
      boundedInteger(value.output_tokens, 1_000_000)) &&
    ['NOT_STARTED', 'COMPLETED', 'FAILED'].includes(
      String(value.perception_status),
    ) &&
    typeof value.perception_reason_code === 'string' &&
    REASON.test(value.perception_reason_code) &&
    ['NOT_EVALUATED', 'ALLOWED', 'DENIED'].includes(
      String(value.policy_decision),
    ) &&
    typeof value.policy_reason_code === 'string' &&
    REASON.test(value.policy_reason_code) &&
    Array.isArray(value.plan_versions) &&
    value.plan_versions.length <= 2 &&
    value.plan_versions.every(
      (item) =>
        isRecord(item) &&
        exactKeys(item, [
          'version',
          'change_reason_code',
          'planned_step_count',
          'created_at',
        ]) &&
        boundedInteger(item.version, 2) &&
        Number(item.version) >= 1 &&
        typeof item.change_reason_code === 'string' &&
        REASON.test(item.change_reason_code) &&
        boundedInteger(item.planned_step_count, 3) &&
        Number(item.planned_step_count) >= 1 &&
        typeof item.created_at === 'string',
    ) &&
    Array.isArray(value.steps) &&
    value.steps.length <= 4 &&
    value.steps.every(isStep) &&
    Array.isArray(value.timeline) &&
    value.timeline.length <= 20 &&
    value.timeline.every(isTimeline)
  )
}

export async function listAgentRuns(
  token: string,
  cursor?: string | null,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  const response = await requestJson<unknown>(`/api/agent-runs?${query}`, {
    token,
    signal,
  })
  if (
    !isRecord(response.data) ||
    !exactKeys(response.data, ['runs', 'next_cursor']) ||
    !Array.isArray(response.data.runs) ||
    !response.data.runs.every(isSummary) ||
    !nullableString(response.data.next_cursor)
  ) {
    throw new ApiError(
      'Backend returned an invalid response.',
      200,
      'invalid_response',
      response.request_id,
    )
  }
  return response as { data: AgentRunHistoryList; request_id: string }
}

export async function getAgentRun(
  token: string,
  runId: string,
  signal?: AbortSignal,
) {
  if (!UUID.test(runId)) {
    throw new ApiError('Agent run is unavailable.', 404, 'not_found', null)
  }
  const response = await requestJson<unknown>(
    `/api/agent-runs/${encodeURIComponent(runId)}`,
    {
      token,
      signal,
    },
  )
  if (!isDetail(response.data)) {
    throw new ApiError(
      'Backend returned an invalid response.',
      200,
      'invalid_response',
      response.request_id,
    )
  }
  return response as { data: AgentRunHistoryDetail; request_id: string }
}
