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

export interface ChatTurn {
  id: string
  question: string
  response: GroundedAnswerData
}
