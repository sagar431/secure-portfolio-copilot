export const CHAT_QUESTION_MAX_LENGTH = 1_000
export const CHAT_TITLE_MAX_LENGTH = 120
export const CHAT_ANSWER_MAX_LENGTH = 12_000
export const CHAT_CLAIM_MAX_LENGTH = 4_000
export const CHAT_LIMITATION_MAX_LENGTH = 1_000
export const CHAT_EXCERPT_MAX_LENGTH = 500

export interface ConversationData {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationListData {
  conversations: ConversationData[]
}

export interface ConversationCreateData {
  conversation: ConversationData
}

export interface CreateConversationRequest {
  title: string | null
}

export interface SendConversationMessageRequest {
  content: string
  response_mode: ResponseMode
}

export type AgentControlMode = 'guided' | 'balanced' | 'autonomous'

export interface RunAgentRequest extends SendConversationMessageRequest {
  agent_control_mode: AgentControlMode
}

export type GroundedAnswerStatus = 'grounded' | 'insufficient_evidence'
export type SafeModelName = 'Gemini 3.1 Flash Lite' | 'Gemini 3.7 Flash'
export type ResponseMode = 'fast' | 'auto' | 'deep'

export interface GroundedClaimData {
  text: string
  citation_ids: string[]
}

export interface GroundedCitationData {
  citation_id: string
  document_id: string
  document_version_id: string
  chunk_id: string
  document_title: string
  version_number: number
  excerpt: string
  page_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  cell_start: string | null
  cell_end: string | null
}

export interface GroundedAnswerData {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  status: GroundedAnswerStatus
  answer: string
  claims: GroundedClaimData[]
  citations: GroundedCitationData[]
  limitations: string[]
  model_name: SafeModelName | null
  route_reason: string | null
  fallback_used: boolean
  requested_response_mode: ResponseMode
  resolved_response_mode: ResponseMode | null
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  estimated_model_cost_usd: string | null
  pricing_snapshot_date: string | null
}

export type AgentTerminalStatus =
  | 'completed'
  | 'refused'
  | 'needs_clarification'
  | 'insufficient_evidence'
  | 'limit_reached'
  | 'failed'

export type AgentTraceEventType =
  | 'perception'
  | 'policy'
  | 'decision'
  | 'gateway'
  | 'tool'
  | 'observation'
  | 'finalization'
  | 'terminal'

export type AgentTraceEventStatus =
  'started' | 'completed' | 'denied' | 'timeout' | 'failed' | 'terminated'

export interface AgentTraceEventData {
  event_id: string
  event_type: AgentTraceEventType
  action_name: string | null
  status: AgentTraceEventStatus
  duration_ms: number
  evidence_reference_ids: string[]
  reason_code: string | null
}

export type CalculationMetric =
  'ebitda_margin' | 'revenue_growth' | 'net_profit_margin'

export interface CalculationInputData {
  name: string
  period: string
  value: number
  unit: 'INR crore'
  citation_id: string
}

export interface CalculationData {
  calculation_id: string
  metric: CalculationMetric
  company_slug: string
  period: string
  formula: string
  trusted_inputs: CalculationInputData[]
  result: number
  unit: 'percent'
  citation_ids: string[]
}

export interface AgentRunData {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  agent_session_id: string
  terminal_status: AgentTerminalStatus
  stopping_reason: string
  answer: string
  claims: GroundedClaimData[]
  citations: GroundedCitationData[]
  limitations: string[]
  calculations: CalculationData[]
  step_count: number
  replan_count: number
  retry_count: number
  trace: AgentTraceEventData[]
  model_name: SafeModelName | null
  route_reason: string | null
  requested_response_mode: ResponseMode
  resolved_response_mode: ResponseMode | null
}

export type ApprovalStatus =
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'SUPERSEDED'
  | 'EXPIRED'
  | 'CANCELLED'
  | 'CONSUMED'

export interface AgentApprovalState {
  approval_id: string
  run_id: string
  status: ApprovalStatus
  action_label: string
  safe_explanation: string
  tool_name: string
  risk_level:
    | 'LOW_READ_ONLY'
    | 'SENSITIVE'
    | 'EXPENSIVE'
    | 'STATE_CHANGING'
    | 'BUDGET_EXPANDING'
    | 'ALWAYS_REQUIRE_APPROVAL'
  resource_type: 'authorized portfolio documents' | 'authorized financial data'
  estimated_cost_class: 'low' | 'standard'
  safe_scope_summary: string
  remaining_budget: { steps: number; tools: number }
  expires_at: string
}

export interface AwaitingAgentApprovalData {
  outcome: 'awaiting_approval'
  conversation_id: string
  user_message_id: string
  agent_session_id: string
  agent_control_mode: AgentControlMode
  approval: AgentApprovalState
}

export interface SafelyTerminatedAgentData {
  outcome: 'terminated'
  run_id: string
  status: 'REJECTED' | 'CANCELLED' | 'FAILED' | 'EXPIRED'
  safe_message: string
}

export type AgentRunResponse =
  AgentRunData | AwaitingAgentApprovalData | SafelyTerminatedAgentData

export interface GroundedChatTurn {
  kind: 'grounded'
  id: string
  question: string
  response: GroundedAnswerData
}

export interface AgentChatTurn {
  kind: 'agent'
  id: string
  question: string
  response: AgentRunData
}

export type ChatTurn = GroundedChatTurn | AgentChatTurn
