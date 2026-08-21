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
}

export type GroundedAnswerStatus = 'grounded' | 'insufficient_evidence'

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
}

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
