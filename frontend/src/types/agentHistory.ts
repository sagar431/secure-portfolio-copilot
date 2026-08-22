import type { ResponseMode, SafeModelName } from './chat'

export type AgentRunStatus =
  | 'CREATED'
  | 'RUNNING'
  | 'AWAITING_APPROVAL'
  | 'COMPLETED'
  | 'REFUSED'
  | 'CLARIFICATION_REQUIRED'
  | 'INSUFFICIENT_EVIDENCE'
  | 'LIMIT_REACHED'
  | 'FAILED'
  | 'CANCELLED'

export interface AgentRunHistorySummary {
  id: string
  conversation_id: string
  response_mode: ResponseMode
  agent_control_mode: 'guided' | 'balanced' | 'autonomous'
  selected_model_tier: 'fast' | 'deep' | null
  selected_model_name: SafeModelName | null
  status: AgentRunStatus
  safe_reason_code: string
  step_count: number
  retry_count: number
  duration_ms: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface AgentRunHistoryList {
  runs: AgentRunHistorySummary[]
  next_cursor: string | null
}

export interface AgentPlanVersionHistory {
  version: number
  change_reason_code: string
  planned_step_count: number
  created_at: string
}

export interface AgentObservationHistory {
  status: 'SUCCESS' | 'DENIED' | 'TIMEOUT' | 'ERROR'
  safe_reason_code: string
  authorized_document_ids: string[]
  authorized_chunk_ids: string[]
  citation_ids: string[]
  evidence_count: number
  retry_count: number
  duration_ms: number
}

export interface AgentStepHistory {
  step_number: number
  plan_version: number
  plan_step_index: number
  action_name: 'TOOL_CALL'
  tool_name: string
  status: 'COMPLETED' | 'DENIED' | 'TIMEOUT' | 'FAILED'
  policy_decision: 'ALLOWED' | 'DENIED'
  safe_reason_code: string
  duration_ms: number
  observation: AgentObservationHistory | null
}

export interface AgentTimelineEventHistory {
  sequence: number
  stage: 'perception' | 'policy' | 'decision' | 'tool' | 'observation' | 'final'
  status: string
  safe_reason_code: string
  summary: string
  tool_name: string | null
  step_number: number | null
  duration_ms: number
}

export interface AgentRunHistoryDetail extends AgentRunHistorySummary {
  final_assistant_message_id: string | null
  input_tokens: number | null
  output_tokens: number | null
  perception_status: 'NOT_STARTED' | 'COMPLETED' | 'FAILED'
  perception_reason_code: string
  policy_decision: 'NOT_EVALUATED' | 'ALLOWED' | 'DENIED'
  policy_reason_code: string
  plan_versions: AgentPlanVersionHistory[]
  steps: AgentStepHistory[]
  timeline: AgentTimelineEventHistory[]
}
