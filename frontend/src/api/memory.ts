import { ApiError, isRecord, requestJson } from './client'
import type { ApiSuccessEnvelope } from '../types/api'
import type {
  CreatePrivateMemoryInput,
  DeletedMemoryData,
  MemoryData,
  MemoryListData,
  MemoryScope,
  MemoryType,
  MemoryOrigin,
  MemoryStatus,
  MemorySourceData,
} from '../types/memory'

const scopes = new Set<MemoryScope>([
  'PRIVATE_USER',
  'FINANCE',
  'LEGAL',
  'SHARED',
])
const departments = new Set(['finance', 'legal', 'shared'])
const visibilities = new Set(['DEPARTMENT_PRIVATE', 'TENANT_SHARED'])
const classifications = new Set([
  'FINANCE_ONLY',
  'LEGAL_ONLY_CONFIDENTIAL',
  'TENANT_SHARED',
])
const memoryTypes = new Set<MemoryType>([
  'SEMANTIC',
  'EPISODIC',
  'CONVERSATION_SUMMARY',
])
const origins = new Set<MemoryOrigin>([
  'EXPLICIT_USER',
  'AUTOMATIC_EXTRACTOR',
  'SYSTEM_SUMMARY',
])
const statuses = new Set<MemoryStatus>([
  'PENDING_CONFIRMATION',
  'ACTIVE',
  'SUPERSEDED',
  'EXPIRED',
  'DELETED',
])

function hasExactKeys(value: Record<string, unknown>, keys: string[]) {
  const actual = Object.keys(value)
  return actual.length === keys.length && keys.every((key) => key in value)
}

function invalid(requestId: string): never {
  throw new ApiError(
    'Backend returned an invalid response.',
    200,
    'invalid_response',
    requestId,
  )
}

function parseSource(value: unknown, requestId: string): MemorySourceData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'chunk_id',
      'document_id',
      'document_version_id',
      'document_name',
    ]) ||
    typeof value.chunk_id !== 'string' ||
    typeof value.document_id !== 'string' ||
    typeof value.document_version_id !== 'string' ||
    typeof value.document_name !== 'string'
  ) {
    return invalid(requestId)
  }
  return {
    chunk_id: value.chunk_id,
    document_id: value.document_id,
    document_version_id: value.document_version_id,
    document_name: value.document_name,
  }
}

function parseMemory(value: unknown, requestId: string): MemoryData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'id',
      'company_id',
      'scope',
      'memory_type',
      'origin',
      'status',
      'owner_user_id',
      'department',
      'visibility',
      'classification',
      'content',
      'normalized_key',
      'reason',
      'confidence',
      'importance',
      'owner_display',
      'tenant_display',
      'company_display',
      'source_conversation',
      'expires_at',
      'created_at',
      'can_delete',
      'can_confirm',
      'sources',
    ]) ||
    typeof value.id !== 'string' ||
    typeof value.company_id !== 'string' ||
    typeof value.scope !== 'string' ||
    !scopes.has(value.scope as MemoryScope) ||
    typeof value.memory_type !== 'string' ||
    !memoryTypes.has(value.memory_type as MemoryType) ||
    typeof value.origin !== 'string' ||
    !origins.has(value.origin as MemoryOrigin) ||
    typeof value.status !== 'string' ||
    !statuses.has(value.status as MemoryStatus) ||
    !(
      value.owner_user_id === null || typeof value.owner_user_id === 'string'
    ) ||
    typeof value.department !== 'string' ||
    !departments.has(value.department) ||
    typeof value.visibility !== 'string' ||
    !visibilities.has(value.visibility) ||
    typeof value.classification !== 'string' ||
    !classifications.has(value.classification) ||
    typeof value.content !== 'string' ||
    !(
      value.normalized_key === null || typeof value.normalized_key === 'string'
    ) ||
    typeof value.reason !== 'string' ||
    typeof value.confidence !== 'number' ||
    typeof value.importance !== 'number' ||
    typeof value.owner_display !== 'string' ||
    typeof value.tenant_display !== 'string' ||
    typeof value.company_display !== 'string' ||
    !(
      value.source_conversation === null ||
      typeof value.source_conversation === 'string'
    ) ||
    typeof value.expires_at !== 'string' ||
    typeof value.created_at !== 'string' ||
    typeof value.can_delete !== 'boolean' ||
    typeof value.can_confirm !== 'boolean' ||
    !Array.isArray(value.sources)
  ) {
    return invalid(requestId)
  }
  return {
    id: value.id,
    company_id: value.company_id,
    scope: value.scope as MemoryScope,
    memory_type: value.memory_type as MemoryType,
    origin: value.origin as MemoryOrigin,
    status: value.status as MemoryStatus,
    owner_user_id: value.owner_user_id,
    department: value.department as MemoryData['department'],
    visibility: value.visibility as MemoryData['visibility'],
    classification: value.classification as MemoryData['classification'],
    content: value.content,
    normalized_key: value.normalized_key,
    reason: value.reason,
    confidence: value.confidence,
    importance: value.importance,
    owner_display: value.owner_display,
    tenant_display: value.tenant_display,
    company_display: value.company_display,
    source_conversation: value.source_conversation,
    expires_at: value.expires_at,
    created_at: value.created_at,
    can_delete: value.can_delete,
    can_confirm: value.can_confirm,
    sources: value.sources.map((item) => parseSource(item, requestId)),
  }
}

function parseList(
  response: ApiSuccessEnvelope<unknown>,
): ApiSuccessEnvelope<MemoryListData> {
  if (
    !isRecord(response.data) ||
    !hasExactKeys(response.data, ['memories']) ||
    !Array.isArray(response.data.memories)
  ) {
    return invalid(response.request_id)
  }
  return {
    request_id: response.request_id,
    data: {
      memories: response.data.memories.map((item) =>
        parseMemory(item, response.request_id),
      ),
    },
  }
}

export function inspectMemories(token: string, signal?: AbortSignal) {
  return requestJson<unknown>('/api/memories', { token, signal }).then(
    parseList,
  )
}

export function createPrivateMemory(
  token: string,
  input: CreatePrivateMemoryInput,
) {
  return requestJson<unknown>('/api/memories', {
    method: 'POST',
    token,
    body: {
      content: input.content,
      company_id: input.companyId,
      scope: 'PRIVATE_USER',
      source_chunk_ids: [],
      expires_in_days: input.expiresInDays,
    },
  }).then((response) => ({
    request_id: response.request_id,
    data: parseMemory(response.data, response.request_id),
  }))
}

export function deleteMemory(token: string, memoryId: string) {
  return requestJson<unknown>(`/api/memories/${memoryId}`, {
    method: 'DELETE',
    token,
  }).then((response): ApiSuccessEnvelope<DeletedMemoryData> => {
    if (
      !isRecord(response.data) ||
      !hasExactKeys(response.data, ['memory_id', 'deleted']) ||
      typeof response.data.memory_id !== 'string' ||
      response.data.deleted !== true
    ) {
      return invalid(response.request_id)
    }
    return {
      request_id: response.request_id,
      data: { memory_id: response.data.memory_id, deleted: true },
    }
  })
}

export function confirmMemory(token: string, memoryId: string) {
  return requestJson<unknown>(`/api/memories/${memoryId}/confirm`, {
    method: 'POST',
    token,
  }).then((response) => ({
    request_id: response.request_id,
    data: parseMemory(response.data, response.request_id),
  }))
}

export function dismissMemory(token: string, memoryId: string) {
  return requestJson<unknown>(`/api/memories/${memoryId}/dismiss`, {
    method: 'POST',
    token,
  }).then((response): ApiSuccessEnvelope<DeletedMemoryData> => {
    if (
      !isRecord(response.data) ||
      response.data.deleted !== true ||
      typeof response.data.memory_id !== 'string'
    ) {
      return invalid(response.request_id)
    }
    return {
      request_id: response.request_id,
      data: { memory_id: response.data.memory_id, deleted: true },
    }
  })
}
