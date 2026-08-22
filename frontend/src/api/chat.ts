import type { ApiSuccessEnvelope } from '../types/api'
import type {
  AgentRunData,
  AgentRunResponse,
  AgentApprovalState,
  AgentControlMode,
  AwaitingAgentApprovalData,
  SafelyTerminatedAgentData,
  AgentTraceEventData,
  CalculationData,
  CalculationInputData,
  ConversationCreateData,
  ConversationData,
  ConversationListData,
  CreateConversationRequest,
  GroundedAnswerData,
  GroundedCitationData,
  GroundedClaimData,
  ResponseMode,
  SendConversationMessageRequest,
} from '../types/chat'
import {
  CHAT_ANSWER_MAX_LENGTH,
  CHAT_CLAIM_MAX_LENGTH,
  CHAT_EXCERPT_MAX_LENGTH,
  CHAT_LIMITATION_MAX_LENGTH,
  CHAT_QUESTION_MAX_LENGTH,
  CHAT_TITLE_MAX_LENGTH,
} from '../types/chat'
import { ApiError, isRecord, requestJson } from './client'

const CONVERSATIONS_PATH = '/api/conversations'
const ISO_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const AGENT_EVIDENCE_REFERENCE = /^ev_[1-9][0-9]{0,2}$/
const APPROVED_STOPPING_REASONS = new Set([
  'citation_validation_failed',
  'clarification_required',
  'completed',
  'duration',
  'insufficient_authorized_evidence',
  'malformed_action',
  'max_replans',
  'max_retrieval_rewrites',
  'max_steps',
  'model_error',
  'plan_exhausted',
  'request_refused',
  'scope_denied',
  'tool_error',
  'tool_timeout',
])
const APPROVED_AGENT_ACTION_NAMES = new Set([
  'portfolio.search_authorized_documents',
  'portfolio.get_document_excerpt',
  'portfolio.calculate_ebitda_margin',
  'portfolio.calculate_revenue_growth',
  'portfolio.calculate_net_profit_margin',
])
const APPROVED_TRACE_REASON_CODES = new Set([
  'ACTION_VALIDATED',
  'AGENT_FAILED_SAFE',
  'AUTHORIZATION_DENIED',
  'AUTHORIZATION_IDENTITY_MISMATCH',
  'CAPABILITY_SHORTLIST_BOUND',
  'CALCULATION_DIVISION_BY_ZERO',
  'CALCULATION_INPUTS_INVALID',
  'CALCULATION_INPUTS_MISSING',
  'CITATION_VALIDATION_FAILED',
  'CITATIONS_VALIDATED',
  'CLARIFICATION_REQUIRED',
  'COMPLETED',
  'DECISION_PRODUCED',
  'DETERMINISTIC_CALCULATION_VALIDATED',
  'DURATION',
  'FINALIZATION_STARTED',
  'INPUT_SCHEMA_REJECTED',
  'INSUFFICIENT_AUTHORIZED_EVIDENCE',
  'MALFORMED_ACTION',
  'MAX_REPLANS',
  'MAX_RETRIEVAL_REWRITES',
  'MAX_STEPS',
  'MODEL_ERROR',
  'OBSERVATION_VALIDATED',
  'OUTPUT_SCHEMA_REJECTED',
  'PERCEPTION_COMPLETED',
  'PLAN_EXHAUSTED',
  'REQUEST_REFUSED',
  'REQUEST_SCOPE_NOT_AUTHORIZED',
  'SCOPE_DENIED',
  'STEP_RESULT_PERCEIVED',
  'TOOL_COMPLETED',
  'TOOL_ERROR',
  'TOOL_FAILED_SAFE',
  'TOOL_NOT_PERMITTED',
  'TOOL_NOT_SHORTLISTED',
  'TOOL_TIMEOUT',
  'TOOL_TRANSIENT_FAILURE',
  'TRUSTED_SCOPE_BOUND',
  'UNKNOWN_TOOL',
])
const AGENT_TERMINAL_STATUSES = new Set([
  'completed',
  'refused',
  'needs_clarification',
  'insufficient_evidence',
  'limit_reached',
  'failed',
])
const AGENT_TRACE_EVENT_TYPES = new Set([
  'perception',
  'policy',
  'decision',
  'gateway',
  'tool',
  'observation',
  'finalization',
  'terminal',
])
const AGENT_TRACE_EVENT_STATUSES = new Set([
  'started',
  'completed',
  'denied',
  'timeout',
  'failed',
  'terminated',
])

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  const actualKeys = Object.keys(value)
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  )
}

function isBoundedString(
  value: unknown,
  maximum: number,
  allowEmpty = false,
): value is string {
  return (
    typeof value === 'string' &&
    value.length <= maximum &&
    (allowEmpty || value.trim().length > 0)
  )
}

function isIdentifier(value: unknown): value is string {
  return isBoundedString(value, 200)
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value)
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    ISO_TIMESTAMP.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' && Number.isInteger(value) && value >= 1)
  )
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isConversation(value: unknown): value is ConversationData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['id', 'title', 'created_at', 'updated_at']) &&
    isUuid(value.id) &&
    isBoundedString(value.title, CHAT_TITLE_MAX_LENGTH) &&
    isTimestamp(value.created_at) &&
    isTimestamp(value.updated_at)
  )
}

function isCitation(value: unknown): value is GroundedCitationData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'citation_id',
      'document_id',
      'document_version_id',
      'chunk_id',
      'document_title',
      'version_number',
      'excerpt',
      'page_number',
      'sheet_name',
      'row_start',
      'row_end',
      'cell_start',
      'cell_end',
    ]) ||
    !isIdentifier(value.citation_id) ||
    !isUuid(value.document_id) ||
    !isUuid(value.document_version_id) ||
    !isUuid(value.chunk_id) ||
    !isBoundedString(value.document_title, 500) ||
    typeof value.version_number !== 'number' ||
    !Number.isInteger(value.version_number) ||
    value.version_number < 1 ||
    !isBoundedString(value.excerpt, CHAT_EXCERPT_MAX_LENGTH) ||
    !isNullablePositiveInteger(value.page_number) ||
    !isNullableString(value.sheet_name) ||
    !isNullablePositiveInteger(value.row_start) ||
    !isNullablePositiveInteger(value.row_end) ||
    !isNullableString(value.cell_start) ||
    !isNullableString(value.cell_end)
  ) {
    return false
  }

  const hasPage = value.page_number !== null
  const hasSheet = value.sheet_name !== null && value.sheet_name.length > 0
  const rowPairMatches =
    (value.row_start === null) === (value.row_end === null) &&
    (value.row_start === null || value.row_end! >= value.row_start)
  const cellPairMatches =
    (value.cell_start === null) === (value.cell_end === null) &&
    (value.cell_start === null ||
      (value.cell_start.trim().length > 0 && value.cell_end!.trim().length > 0))
  const spreadsheetCoordinatesRequireSheet =
    hasSheet ||
    (value.row_start === null &&
      value.row_end === null &&
      value.cell_start === null &&
      value.cell_end === null)

  return (
    (hasPage || hasSheet) &&
    !(hasPage && hasSheet) &&
    rowPairMatches &&
    cellPairMatches &&
    spreadsheetCoordinatesRequireSheet
  )
}

function isClaim(value: unknown): value is GroundedClaimData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['text', 'citation_ids']) &&
    isBoundedString(value.text, CHAT_CLAIM_MAX_LENGTH) &&
    Array.isArray(value.citation_ids) &&
    value.citation_ids.length > 0 &&
    value.citation_ids.every(isIdentifier) &&
    new Set(value.citation_ids).size === value.citation_ids.length
  )
}

function hasValidCitationGraph(
  claims: GroundedClaimData[],
  citations: GroundedCitationData[],
) {
  const citationIds = new Set(citations.map((citation) => citation.citation_id))
  if (citationIds.size !== citations.length) {
    return false
  }
  if (claims.length === 0 || citations.length === 0) {
    return claims.length === 0 && citations.length === 0
  }
  const referencedCitationIds = new Set(
    claims.flatMap((claim) => claim.citation_ids),
  )
  return (
    referencedCitationIds.size === citationIds.size &&
    [...referencedCitationIds].every((citationId) =>
      citationIds.has(citationId),
    )
  )
}

function isExactEnvelope<T>(
  response: ApiSuccessEnvelope<unknown>,
  validateData: (value: unknown) => value is T,
): response is ApiSuccessEnvelope<T> {
  return (
    hasOnlyKeys(response as unknown as Record<string, unknown>, [
      'data',
      'request_id',
    ]) &&
    isIdentifier(response.request_id) &&
    validateData(response.data)
  )
}

function isConversationListData(value: unknown): value is ConversationListData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['conversations']) &&
    Array.isArray(value.conversations) &&
    value.conversations.every(isConversation) &&
    new Set(value.conversations.map((conversation) => conversation.id)).size ===
      value.conversations.length
  )
}

function isConversationCreateData(
  value: unknown,
): value is ConversationCreateData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['conversation']) &&
    isConversation(value.conversation)
  )
}

function isGroundedAnswerData(value: unknown): value is GroundedAnswerData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'conversation_id',
      'user_message_id',
      'assistant_message_id',
      'status',
      'answer',
      'claims',
      'citations',
      'limitations',
      'model_name',
      'route_reason',
      'fallback_used',
      'requested_response_mode',
      'resolved_response_mode',
      'input_tokens',
      'output_tokens',
      'latency_ms',
      'estimated_model_cost_usd',
      'pricing_snapshot_date',
    ]) ||
    !isUuid(value.conversation_id) ||
    !isUuid(value.user_message_id) ||
    !isUuid(value.assistant_message_id) ||
    (value.status !== 'grounded' && value.status !== 'insufficient_evidence') ||
    !isBoundedString(value.answer, CHAT_ANSWER_MAX_LENGTH) ||
    !Array.isArray(value.claims) ||
    !value.claims.every(isClaim) ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isCitation) ||
    !Array.isArray(value.limitations) ||
    !value.limitations.every((limitation) =>
      isBoundedString(limitation, CHAT_LIMITATION_MAX_LENGTH),
    ) ||
    !isSafeModelName(value.model_name) ||
    !isSafeRouteReason(value.route_reason) ||
    typeof value.fallback_used !== 'boolean' ||
    !isResponseMode(value.requested_response_mode) ||
    !isNullableResponseMode(value.resolved_response_mode) ||
    !isNullableTokenCount(value.input_tokens) ||
    !isNullableTokenCount(value.output_tokens) ||
    !isNullableLatency(value.latency_ms) ||
    !isNullableCost(value.estimated_model_cost_usd) ||
    !isNullablePricingDate(value.pricing_snapshot_date)
  ) {
    return false
  }

  if (value.status === 'insufficient_evidence') {
    return value.claims.length === 0 && value.citations.length === 0
  }
  return (
    value.claims.length > 0 &&
    value.citations.length > 0 &&
    hasValidCitationGraph(value.claims, value.citations)
  )
}

function isSafeCounter(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 1_000
  )
}

const SAFE_MODEL_NAMES = new Set(['Gemini 3.1 Flash Lite', 'Gemini 3.7 Flash'])
const SAFE_ROUTE_REASONS = new Set([
  'USER_REQUESTED_DEEP',
  'FAST_MODE_ELIGIBLE',
  'DEEP_MODE_REQUIRED',
  'SIMPLE_LOW_RISK',
  'MULTI_DOCUMENT',
  'LOW_CONFIDENCE',
  'COMPLEX_REQUEST',
  'AGENTIC_REQUEST',
])

const RESPONSE_MODES = new Set(['fast', 'auto', 'deep'])

function isResponseMode(value: unknown): value is ResponseMode {
  return typeof value === 'string' && RESPONSE_MODES.has(value)
}

function isNullableResponseMode(value: unknown): value is ResponseMode | null {
  return value === null || isResponseMode(value)
}

function isNullableTokenCount(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' &&
      Number.isInteger(value) &&
      value >= 0 &&
      value <= 10_000_000)
  )
}

function isNullableLatency(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === 'number' &&
      Number.isInteger(value) &&
      value >= 0 &&
      value <= 3_600_000)
  )
}

function isNullableCost(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === 'string' && /^\d+\.\d{1,12}$/.test(value))
  )
}

function isNullablePricingDate(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value))
  )
}

function isSafeModelName(value: unknown) {
  return (
    value === null || (typeof value === 'string' && SAFE_MODEL_NAMES.has(value))
  )
}

function isSafeRouteReason(value: unknown) {
  return (
    value === null ||
    (typeof value === 'string' && SAFE_ROUTE_REASONS.has(value))
  )
}

function isCalculationInput(value: unknown): value is CalculationInputData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['name', 'period', 'value', 'unit', 'citation_id']) &&
    isBoundedString(value.name, 80) &&
    typeof value.period === 'string' &&
    /^FY[0-9]{4}$/.test(value.period) &&
    typeof value.value === 'number' &&
    Number.isFinite(value.value) &&
    Math.abs(value.value) <= 1_000_000_000_000 &&
    value.unit === 'INR crore' &&
    typeof value.citation_id === 'string' &&
    AGENT_EVIDENCE_REFERENCE.test(value.citation_id)
  )
}

function isCalculation(value: unknown): value is CalculationData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'calculation_id',
      'metric',
      'company_slug',
      'period',
      'formula',
      'trusted_inputs',
      'result',
      'unit',
      'citation_ids',
    ]) ||
    !isUuid(value.calculation_id) ||
    !['ebitda_margin', 'revenue_growth', 'net_profit_margin'].includes(
      String(value.metric),
    ) ||
    typeof value.company_slug !== 'string' ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.company_slug) ||
    typeof value.period !== 'string' ||
    !/^FY[0-9]{4}$/.test(value.period) ||
    !isBoundedString(value.formula, 400) ||
    !Array.isArray(value.trusted_inputs) ||
    value.trusted_inputs.length < 2 ||
    value.trusted_inputs.length > 6 ||
    !value.trusted_inputs.every(isCalculationInput) ||
    typeof value.result !== 'number' ||
    !Number.isFinite(value.result) ||
    Math.abs(value.result) > 1_000_000 ||
    value.unit !== 'percent' ||
    !Array.isArray(value.citation_ids) ||
    !value.citation_ids.every(
      (item) => typeof item === 'string' && AGENT_EVIDENCE_REFERENCE.test(item),
    )
  ) {
    return false
  }
  const inputCitationIds = value.trusted_inputs.map(
    (input) => input.citation_id,
  )
  return (
    new Set(value.citation_ids).size === value.citation_ids.length &&
    value.citation_ids.length === inputCitationIds.length &&
    value.citation_ids.every((item, index) => item === inputCitationIds[index])
  )
}

function isAgentTraceEvent(value: unknown): value is AgentTraceEventData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'event_id',
      'event_type',
      'action_name',
      'status',
      'duration_ms',
      'evidence_reference_ids',
      'reason_code',
    ]) &&
    isUuid(value.event_id) &&
    typeof value.event_type === 'string' &&
    AGENT_TRACE_EVENT_TYPES.has(value.event_type) &&
    (value.action_name === null ||
      (typeof value.action_name === 'string' &&
        APPROVED_AGENT_ACTION_NAMES.has(value.action_name))) &&
    typeof value.status === 'string' &&
    AGENT_TRACE_EVENT_STATUSES.has(value.status) &&
    typeof value.duration_ms === 'number' &&
    Number.isInteger(value.duration_ms) &&
    value.duration_ms >= 0 &&
    value.duration_ms <= 3_600_000 &&
    Array.isArray(value.evidence_reference_ids) &&
    value.evidence_reference_ids.length <= 100 &&
    value.evidence_reference_ids.every(
      (reference) =>
        typeof reference === 'string' &&
        AGENT_EVIDENCE_REFERENCE.test(reference),
    ) &&
    new Set(value.evidence_reference_ids).size ===
      value.evidence_reference_ids.length &&
    (value.reason_code === null ||
      (typeof value.reason_code === 'string' &&
        APPROVED_TRACE_REASON_CODES.has(value.reason_code)))
  )
}

function isAgentRunData(value: unknown): value is AgentRunData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'conversation_id',
      'user_message_id',
      'assistant_message_id',
      'agent_session_id',
      'terminal_status',
      'stopping_reason',
      'answer',
      'claims',
      'citations',
      'limitations',
      'calculations',
      'step_count',
      'replan_count',
      'retry_count',
      'trace',
      'model_name',
      'route_reason',
      'requested_response_mode',
      'resolved_response_mode',
    ]) ||
    !isUuid(value.conversation_id) ||
    !isUuid(value.user_message_id) ||
    !isUuid(value.assistant_message_id) ||
    !isUuid(value.agent_session_id) ||
    typeof value.terminal_status !== 'string' ||
    !AGENT_TERMINAL_STATUSES.has(value.terminal_status) ||
    typeof value.stopping_reason !== 'string' ||
    !APPROVED_STOPPING_REASONS.has(value.stopping_reason) ||
    !isBoundedString(value.answer, CHAT_ANSWER_MAX_LENGTH) ||
    !Array.isArray(value.claims) ||
    !value.claims.every(isClaim) ||
    !Array.isArray(value.citations) ||
    !value.citations.every(isCitation) ||
    !Array.isArray(value.limitations) ||
    !value.limitations.every((limitation) =>
      isBoundedString(limitation, CHAT_LIMITATION_MAX_LENGTH),
    ) ||
    !Array.isArray(value.calculations) ||
    value.calculations.length > 1 ||
    !value.calculations.every(isCalculation) ||
    !isSafeCounter(value.step_count) ||
    !isSafeCounter(value.replan_count) ||
    !isSafeCounter(value.retry_count) ||
    !Array.isArray(value.trace) ||
    !isSafeModelName(value.model_name) ||
    !isSafeRouteReason(value.route_reason) ||
    !isResponseMode(value.requested_response_mode) ||
    !isNullableResponseMode(value.resolved_response_mode) ||
    value.trace.length === 0 ||
    value.trace.length > 256 ||
    !value.trace.every(isAgentTraceEvent)
  ) {
    return false
  }

  const finalTraceEvent = value.trace.at(-1)
  if (
    new Set(value.trace.map((event) => event.event_id)).size !==
      value.trace.length ||
    finalTraceEvent?.event_type !== 'terminal' ||
    (value.terminal_status === 'completed'
      ? finalTraceEvent.status !== 'completed'
      : finalTraceEvent.status !== 'terminated')
  ) {
    return false
  }

  if (value.terminal_status === 'completed') {
    const validGrounding =
      value.claims.length > 0 &&
      value.citations.length > 0 &&
      hasValidCitationGraph(value.claims, value.citations)
    if (!validGrounding) return false
    const calculations = value.calculations
    const citations = value.citations
    return calculations.every((calculation) =>
      calculation.citation_ids.every((citationId) =>
        citations.some((citation) => citation.citation_id === citationId),
      ),
    )
  }
  return (
    value.claims.length === 0 &&
    value.citations.length === 0 &&
    value.calculations.length === 0
  )
}

const CONTROL_MODES = new Set(['guided', 'balanced', 'autonomous'])
const APPROVAL_STATUSES = new Set([
  'PENDING',
  'APPROVED',
  'REJECTED',
  'SUPERSEDED',
  'EXPIRED',
  'CANCELLED',
  'CONSUMED',
])
const APPROVAL_RISKS = new Set([
  'LOW_READ_ONLY',
  'SENSITIVE',
  'EXPENSIVE',
  'STATE_CHANGING',
  'BUDGET_EXPANDING',
  'ALWAYS_REQUIRE_APPROVAL',
])

function isApprovalState(value: unknown): value is AgentApprovalState {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'approval_id',
      'run_id',
      'status',
      'action_label',
      'safe_explanation',
      'tool_name',
      'risk_level',
      'resource_type',
      'estimated_cost_class',
      'safe_scope_summary',
      'remaining_budget',
      'expires_at',
    ]) &&
    isUuid(value.approval_id) &&
    isUuid(value.run_id) &&
    typeof value.status === 'string' &&
    APPROVAL_STATUSES.has(value.status) &&
    isBoundedString(value.action_label, 80) &&
    isBoundedString(value.safe_explanation, 180) &&
    typeof value.tool_name === 'string' &&
    APPROVED_AGENT_ACTION_NAMES.has(value.tool_name) &&
    typeof value.risk_level === 'string' &&
    APPROVAL_RISKS.has(value.risk_level) &&
    (value.resource_type === 'authorized portfolio documents' ||
      value.resource_type === 'authorized financial data') &&
    (value.estimated_cost_class === 'low' ||
      value.estimated_cost_class === 'standard') &&
    isBoundedString(value.safe_scope_summary, 160) &&
    isRecord(value.remaining_budget) &&
    hasOnlyKeys(value.remaining_budget, ['steps', 'tools']) &&
    isSafeCounter(value.remaining_budget.steps) &&
    isSafeCounter(value.remaining_budget.tools) &&
    isTimestamp(value.expires_at)
  )
}

function isAwaitingApproval(
  value: unknown,
): value is AwaitingAgentApprovalData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'outcome',
      'conversation_id',
      'user_message_id',
      'agent_session_id',
      'agent_control_mode',
      'approval',
    ]) &&
    value.outcome === 'awaiting_approval' &&
    isUuid(value.conversation_id) &&
    isUuid(value.user_message_id) &&
    isUuid(value.agent_session_id) &&
    typeof value.agent_control_mode === 'string' &&
    CONTROL_MODES.has(value.agent_control_mode) &&
    isApprovalState(value.approval) &&
    value.approval.run_id === value.agent_session_id
  )
}

function isSafelyTerminated(
  value: unknown,
): value is SafelyTerminatedAgentData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ['outcome', 'run_id', 'status', 'safe_message']) &&
    value.outcome === 'terminated' &&
    isUuid(value.run_id) &&
    ['REJECTED', 'CANCELLED', 'FAILED', 'EXPIRED'].includes(
      String(value.status),
    ) &&
    isBoundedString(value.safe_message, 180)
  )
}

function isAgentRunResponse(value: unknown): value is AgentRunResponse {
  return (
    isAgentRunData(value) ||
    isAwaitingApproval(value) ||
    isSafelyTerminated(value)
  )
}

function invalidResponse(requestId: string | null) {
  return new ApiError(
    'Backend returned an invalid response.',
    200,
    'invalid_response',
    requestId,
  )
}

function validateTitle(title: string | null): CreateConversationRequest {
  if (title === null) {
    return { title: null }
  }
  const trimmedTitle = title.trim()
  if (!trimmedTitle || trimmedTitle.length > CHAT_TITLE_MAX_LENGTH) {
    throw new ApiError(
      `Conversation title must contain between 1 and ${CHAT_TITLE_MAX_LENGTH} characters.`,
      0,
      'invalid_conversation_title',
      null,
    )
  }
  return { title: trimmedTitle }
}

function validateMessage(
  content: string,
  responseMode: ResponseMode,
): SendConversationMessageRequest {
  const trimmedContent = content.trim()
  if (!trimmedContent || trimmedContent.length > CHAT_QUESTION_MAX_LENGTH) {
    throw new ApiError(
      `Question must contain between 1 and ${CHAT_QUESTION_MAX_LENGTH} characters.`,
      0,
      'invalid_chat_question',
      null,
    )
  }
  if (!isResponseMode(responseMode)) {
    throw new ApiError(
      'Select a valid response mode.',
      0,
      'invalid_response_mode',
      null,
    )
  }
  return { content: trimmedContent, response_mode: responseMode }
}

export async function listConversations(
  token: string,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<ConversationListData>> {
  const response = await requestJson<unknown>(CONVERSATIONS_PATH, {
    token,
    signal,
  })
  if (!isExactEnvelope(response, isConversationListData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function createConversation(
  token: string,
  title: string | null,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<ConversationCreateData>> {
  const response = await requestJson<unknown>(CONVERSATIONS_PATH, {
    method: 'POST',
    token,
    body: validateTitle(title),
    signal,
  })
  if (!isExactEnvelope(response, isConversationCreateData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function sendConversationMessage(
  token: string,
  conversationId: string,
  content: string,
  signal?: AbortSignal,
  responseMode: ResponseMode = 'auto',
): Promise<ApiSuccessEnvelope<GroundedAnswerData>> {
  if (!isUuid(conversationId)) {
    throw new ApiError(
      'Select a valid conversation.',
      0,
      'invalid_conversation_id',
      null,
    )
  }
  const response = await requestJson<unknown>(
    `${CONVERSATIONS_PATH}/${encodeURIComponent(conversationId)}/messages`,
    {
      method: 'POST',
      token,
      body: validateMessage(content, responseMode),
      signal,
    },
  )
  if (!isExactEnvelope(response, isGroundedAnswerData)) {
    throw invalidResponse(response.request_id ?? null)
  }
  if (response.data.conversation_id !== conversationId) {
    throw invalidResponse(response.request_id)
  }
  return response
}

export async function runConversationAgent(
  token: string,
  conversationId: string,
  content: string,
  signal?: AbortSignal,
  responseMode: ResponseMode = 'auto',
  agentControlMode: AgentControlMode = 'balanced',
): Promise<ApiSuccessEnvelope<AgentRunData | AwaitingAgentApprovalData>> {
  if (!isUuid(conversationId)) {
    throw new ApiError(
      'Select a valid conversation.',
      0,
      'invalid_conversation_id',
      null,
    )
  }
  const response = await requestJson<unknown>(
    `${CONVERSATIONS_PATH}/${encodeURIComponent(conversationId)}/agent-runs`,
    {
      method: 'POST',
      token,
      body: {
        ...validateMessage(content, responseMode),
        agent_control_mode: agentControlMode,
      },
      signal,
    },
  )
  if (
    !isExactEnvelope(
      response,
      (value): value is AgentRunData | AwaitingAgentApprovalData =>
        isAgentRunData(value) || isAwaitingApproval(value),
    )
  ) {
    throw invalidResponse(response.request_id ?? null)
  }
  if (response.data.conversation_id !== conversationId) {
    throw invalidResponse(response.request_id)
  }
  return response
}

const APPROVAL_BASE = '/api/agent-runs'

export async function resolveAgentApproval(
  token: string,
  runId: string,
  approvalId: string,
  action: 'approve_once' | 'reject',
): Promise<ApiSuccessEnvelope<AgentRunResponse>> {
  const response = await requestJson<unknown>(
    `${APPROVAL_BASE}/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/resolve`,
    { method: 'POST', token, body: { action } },
  )
  if (!isExactEnvelope(response, isAgentRunResponse)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function stopAgentRun(token: string, runId: string) {
  const response = await requestJson<unknown>(
    `${APPROVAL_BASE}/${encodeURIComponent(runId)}/stop`,
    { method: 'POST', token },
  )
  if (!isExactEnvelope(response, isSafelyTerminated)) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}

export async function changeAgentRequest(
  token: string,
  runId: string,
  approvalId: string,
  content: string,
): Promise<ApiSuccessEnvelope<AgentRunData | AwaitingAgentApprovalData>> {
  const response = await requestJson<unknown>(
    `${APPROVAL_BASE}/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/change-request`,
    { method: 'POST', token, body: { content: content.trim() } },
  )
  if (
    !isExactEnvelope(
      response,
      (value): value is AgentRunData | AwaitingAgentApprovalData =>
        isAgentRunData(value) || isAwaitingApproval(value),
    )
  ) {
    throw invalidResponse(response.request_id ?? null)
  }
  return response
}
