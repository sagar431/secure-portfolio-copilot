export type MemoryScope = 'PRIVATE_USER' | 'FINANCE' | 'LEGAL' | 'SHARED'
export type MemoryType = 'SEMANTIC' | 'EPISODIC' | 'CONVERSATION_SUMMARY'
export type MemoryOrigin =
  'EXPLICIT_USER' | 'AUTOMATIC_EXTRACTOR' | 'SYSTEM_SUMMARY'
export type MemoryStatus =
  'PENDING_CONFIRMATION' | 'ACTIVE' | 'SUPERSEDED' | 'EXPIRED' | 'DELETED'

export interface MemorySourceData {
  chunk_id: string
  document_id: string
  document_version_id: string
  document_name: string
}

export interface MemoryData {
  id: string
  company_id: string
  scope: MemoryScope
  memory_type: MemoryType
  origin: MemoryOrigin
  status: MemoryStatus
  owner_user_id: string | null
  department: 'finance' | 'legal' | 'shared'
  visibility: 'DEPARTMENT_PRIVATE' | 'TENANT_SHARED'
  classification: 'FINANCE_ONLY' | 'LEGAL_ONLY_CONFIDENTIAL' | 'TENANT_SHARED'
  content: string
  normalized_key: string | null
  reason: string
  confidence: number
  importance: number
  owner_display: string
  tenant_display: string
  company_display: string
  source_conversation: string | null
  expires_at: string
  created_at: string
  can_delete: boolean
  can_confirm: boolean
  sources: MemorySourceData[]
}

export interface MemoryListData {
  memories: MemoryData[]
}

export interface CreatePrivateMemoryInput {
  companyId: string
  content: string
  expiresInDays: number
}

export interface DeletedMemoryData {
  memory_id: string
  deleted: true
}
