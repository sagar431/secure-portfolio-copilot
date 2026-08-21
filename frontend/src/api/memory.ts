import { ApiError, isRecord, requestJson } from './client'
import type { ApiSuccessEnvelope } from '../types/api'
import type {
  CreatePrivateMemoryInput,
  DeletedMemoryData,
  MemoryData,
  MemoryListData,
  MemoryScope,
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
    !hasExactKeys(value, ['chunk_id', 'document_id', 'document_version_id']) ||
    typeof value.chunk_id !== 'string' ||
    typeof value.document_id !== 'string' ||
    typeof value.document_version_id !== 'string'
  ) {
    return invalid(requestId)
  }
  return {
    chunk_id: value.chunk_id,
    document_id: value.document_id,
    document_version_id: value.document_version_id,
  }
}

function parseMemory(value: unknown, requestId: string): MemoryData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'id',
      'company_id',
      'scope',
      'owner_user_id',
      'department',
      'visibility',
      'classification',
      'content',
      'expires_at',
      'created_at',
      'can_delete',
      'sources',
    ]) ||
    typeof value.id !== 'string' ||
    typeof value.company_id !== 'string' ||
    typeof value.scope !== 'string' ||
    !scopes.has(value.scope as MemoryScope) ||
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
    typeof value.expires_at !== 'string' ||
    typeof value.created_at !== 'string' ||
    typeof value.can_delete !== 'boolean' ||
    !Array.isArray(value.sources)
  ) {
    return invalid(requestId)
  }
  return {
    id: value.id,
    company_id: value.company_id,
    scope: value.scope as MemoryScope,
    owner_user_id: value.owner_user_id,
    department: value.department as MemoryData['department'],
    visibility: value.visibility as MemoryData['visibility'],
    classification: value.classification as MemoryData['classification'],
    content: value.content,
    expires_at: value.expires_at,
    created_at: value.created_at,
    can_delete: value.can_delete,
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
