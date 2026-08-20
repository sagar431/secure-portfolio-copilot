import { ApiError, isRecord, requestJson } from './client'
import type { ApiSuccessEnvelope } from '../types/api'
import type {
  AuthorizedSearchData,
  AuthorizedSearchRequest,
  SearchDocumentData,
  SearchScopeGrantData,
  SearchSourceData,
} from '../types/search'
import {
  SEARCH_EXCERPT_MAX_LENGTH,
  SEARCH_QUERY_MAX_LENGTH,
  SEARCH_TOP_K_MAX,
  SEARCH_TOP_K_MIN,
} from '../types/search'

const SEARCH_PATH = '/api/development/authorized-search'
const SEARCH_STATUSES = new Set(['ready', 'indexing'])
const SOURCE_TYPES = new Set(['PDF', 'XLSX', 'CSV', 'UNKNOWN'])
const DOCUMENT_TYPES = new Set([
  'FINANCIAL_REPORT',
  'LEGAL_AGREEMENT',
  'POLICY',
  'EMAIL',
  'SPREADSHEET',
  'OTHER',
])
const VISIBILITIES = new Set(['DEPARTMENT_PRIVATE', 'TENANT_SHARED'])
const CLASSIFICATIONS = new Set([
  'FINANCE_ONLY',
  'LEGAL_ONLY_CONFIDENTIAL',
  'TENANT_SHARED',
])

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isNullableNumber(value: unknown): value is number | null {
  return (
    value === null || (typeof value === 'number' && Number.isInteger(value))
  )
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isScopeGrant(value: unknown): value is SearchScopeGrantData {
  return (
    isRecord(value) &&
    isRecord(value.workspace) &&
    typeof value.workspace.id === 'string' &&
    typeof value.workspace.slug === 'string' &&
    typeof value.workspace.name === 'string' &&
    isStringArray(value.company_ids) &&
    isStringArray(value.company_slugs) &&
    isStringArray(value.query_departments)
  )
}

function isSource(value: unknown): value is SearchSourceData {
  return (
    isRecord(value) &&
    isNullableNumber(value.page_number) &&
    isNullableString(value.sheet_name) &&
    isNullableNumber(value.row_start) &&
    isNullableNumber(value.row_end) &&
    isNullableString(value.cell_start) &&
    isNullableString(value.cell_end)
  )
}

function isDocument(value: unknown): value is SearchDocumentData {
  return (
    isRecord(value) &&
    typeof value.filename === 'string' &&
    typeof value.source_type === 'string' &&
    SOURCE_TYPES.has(value.source_type) &&
    typeof value.document_type === 'string' &&
    DOCUMENT_TYPES.has(value.document_type) &&
    isNullableString(value.reporting_period) &&
    typeof value.tenant_slug === 'string' &&
    typeof value.company_slug === 'string' &&
    typeof value.department === 'string' &&
    typeof value.visibility === 'string' &&
    VISIBILITIES.has(value.visibility) &&
    typeof value.classification === 'string' &&
    CLASSIFICATIONS.has(value.classification)
  )
}

function isAuthorizedSearchData(value: unknown): value is AuthorizedSearchData {
  if (
    !isRecord(value) ||
    typeof value.status !== 'string' ||
    !SEARCH_STATUSES.has(value.status) ||
    typeof value.query !== 'string' ||
    !Number.isInteger(value.top_k) ||
    (value.top_k as number) < SEARCH_TOP_K_MIN ||
    (value.top_k as number) > SEARCH_TOP_K_MAX ||
    !isNonNegativeInteger(value.result_count) ||
    !isRecord(value.authorized_scope) ||
    !Array.isArray(value.authorized_scope.grants) ||
    !value.authorized_scope.grants.every(isScopeGrant) ||
    !isRecord(value.indexing) ||
    typeof value.indexing.status !== 'string' ||
    !SEARCH_STATUSES.has(value.indexing.status) ||
    !isNonNegativeInteger(value.indexing.active_chunk_count) ||
    !isNonNegativeInteger(value.indexing.indexed_document_count) ||
    !Array.isArray(value.results) ||
    value.results.length !== value.result_count ||
    value.results.length > (value.top_k as number)
  ) {
    return false
  }
  return value.results.every(
    (result) =>
      isRecord(result) &&
      typeof result.chunk_id === 'string' &&
      typeof result.document_id === 'string' &&
      typeof result.document_version_id === 'string' &&
      Number.isInteger(result.version_number) &&
      (result.version_number as number) >= 1 &&
      typeof result.excerpt === 'string' &&
      result.excerpt.length <= SEARCH_EXCERPT_MAX_LENGTH &&
      typeof result.score === 'number' &&
      Number.isFinite(result.score) &&
      result.score >= 0 &&
      isSource(result.source) &&
      isDocument(result.document),
  )
}

function validateInput(input: AuthorizedSearchRequest) {
  const query = input.query.trim()
  if (!query || query.length > SEARCH_QUERY_MAX_LENGTH) {
    throw new ApiError(
      `Query must contain between 1 and ${SEARCH_QUERY_MAX_LENGTH} characters.`,
      0,
      'invalid_search_query',
      null,
    )
  }
  if (
    !Number.isInteger(input.top_k) ||
    input.top_k < SEARCH_TOP_K_MIN ||
    input.top_k > SEARCH_TOP_K_MAX
  ) {
    throw new ApiError(
      `Top results must be between ${SEARCH_TOP_K_MIN} and ${SEARCH_TOP_K_MAX}.`,
      0,
      'invalid_top_k',
      null,
    )
  }
  return { query, top_k: input.top_k }
}

export async function searchAuthorizedDocuments(
  token: string,
  input: AuthorizedSearchRequest,
  signal?: AbortSignal,
): Promise<ApiSuccessEnvelope<AuthorizedSearchData>> {
  const response = await requestJson<unknown>(SEARCH_PATH, {
    method: 'POST',
    token,
    body: validateInput(input),
    signal,
  })
  if (!isAuthorizedSearchData(response.data)) {
    throw new ApiError(
      'Backend returned an invalid response.',
      200,
      'invalid_response',
      response.request_id,
    )
  }
  return { data: response.data, request_id: response.request_id }
}
