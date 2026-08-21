export type MemoryScope = 'PRIVATE_USER' | 'FINANCE' | 'LEGAL' | 'SHARED'

export interface MemorySourceData {
  chunk_id: string
  document_id: string
  document_version_id: string
}

export interface MemoryData {
  id: string
  company_id: string
  scope: MemoryScope
  owner_user_id: string | null
  department: 'finance' | 'legal' | 'shared'
  visibility: 'DEPARTMENT_PRIVATE' | 'TENANT_SHARED'
  classification: 'FINANCE_ONLY' | 'LEGAL_ONLY_CONFIDENTIAL' | 'TENANT_SHARED'
  content: string
  expires_at: string
  created_at: string
  can_delete: boolean
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
