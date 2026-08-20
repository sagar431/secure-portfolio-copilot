import { ApiError, isRecord, requestJson } from './client'
import type { ApiSuccessEnvelope } from '../types/api'
import type {
  AuthorizedSearchData,
  AuthorizedSearchRequest,
  AuthorizedSearchResultData,
  SearchDocumentData,
  SearchEvaluationSummaryData,
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
const SEARCH_STATUSES = new Set(['ready', 'indexing', 'degraded'])
const EMBEDDING_STATUSES = new Set([
  'ready',
  'indexing',
  'degraded',
  'unavailable',
])
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

function hasOnlyKeys(value: Record<string, unknown>, keys: string[]) {
  const actualKeys = Object.keys(value)
  return (
    actualKeys.length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  )
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

function isUnitInterval(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  )
}

function hasSameSource(left: SearchSourceData, right: SearchSourceData) {
  return (
    left.page_number === right.page_number &&
    left.sheet_name === right.sheet_name &&
    left.row_start === right.row_start &&
    left.row_end === right.row_end &&
    left.cell_start === right.cell_start &&
    left.cell_end === right.cell_end
  )
}

function isScopeGrant(value: unknown): value is SearchScopeGrantData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'workspace',
      'company_ids',
      'company_slugs',
      'query_departments',
    ]) &&
    isRecord(value.workspace) &&
    hasOnlyKeys(value.workspace, ['id', 'slug', 'name']) &&
    typeof value.workspace.id === 'string' &&
    typeof value.workspace.slug === 'string' &&
    typeof value.workspace.name === 'string' &&
    isStringArray(value.company_ids) &&
    isStringArray(value.company_slugs) &&
    isStringArray(value.query_departments)
  )
}

function hasSourceFields(
  value: Record<string, unknown>,
): value is Record<string, unknown> & SearchSourceData {
  return (
    isNullableNumber(value.page_number) &&
    isNullableString(value.sheet_name) &&
    isNullableNumber(value.row_start) &&
    isNullableNumber(value.row_end) &&
    isNullableString(value.cell_start) &&
    isNullableString(value.cell_end)
  )
}

function isSource(value: unknown): value is SearchSourceData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'page_number',
      'sheet_name',
      'row_start',
      'row_end',
      'cell_start',
      'cell_end',
    ]) &&
    hasSourceFields(value)
  )
}

function isDocument(value: unknown): value is SearchDocumentData {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      'filename',
      'source_type',
      'document_type',
      'reporting_period',
      'tenant_slug',
      'company_slug',
      'department',
      'visibility',
      'classification',
    ]) &&
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

function isEvaluationSummary(
  value: unknown,
): value is SearchEvaluationSummaryData {
  if (!isRecord(value) || typeof value.status !== 'string') {
    return false
  }
  if (value.status === 'not_run') {
    return Object.keys(value).length === 1
  }
  return (
    value.status === 'complete' &&
    hasOnlyKeys(value, [
      'status',
      'dataset_name',
      'curated_query_count',
      'recall_at_5',
      'expected_top_5_hits',
      'authorization_leak_count',
    ]) &&
    typeof value.dataset_name === 'string' &&
    value.dataset_name.length > 0 &&
    isNonNegativeInteger(value.curated_query_count) &&
    isUnitInterval(value.recall_at_5) &&
    isNonNegativeInteger(value.expected_top_5_hits) &&
    value.expected_top_5_hits <= value.curated_query_count &&
    isNonNegativeInteger(value.authorization_leak_count)
  )
}

function isSearchResult(value: unknown): value is AuthorizedSearchResultData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'chunk_id',
      'document_id',
      'document_version_id',
      'version_number',
      'excerpt',
      'scores',
      'source',
      'citation',
      'document',
    ]) ||
    typeof value.chunk_id !== 'string' ||
    typeof value.document_id !== 'string' ||
    typeof value.document_version_id !== 'string' ||
    !Number.isInteger(value.version_number) ||
    (value.version_number as number) < 1 ||
    typeof value.excerpt !== 'string' ||
    value.excerpt.length > SEARCH_EXCERPT_MAX_LENGTH ||
    !isRecord(value.scores) ||
    !hasOnlyKeys(value.scores, ['keyword', 'vector', 'final']) ||
    !isUnitInterval(value.scores.keyword) ||
    !isUnitInterval(value.scores.vector) ||
    !isUnitInterval(value.scores.final) ||
    !isSource(value.source) ||
    !isRecord(value.citation) ||
    !hasOnlyKeys(value.citation, [
      'chunk_id',
      'document_id',
      'document_version_id',
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
    typeof value.citation.chunk_id !== 'string' ||
    typeof value.citation.document_id !== 'string' ||
    typeof value.citation.document_version_id !== 'string' ||
    typeof value.citation.document_title !== 'string' ||
    value.citation.document_title.length === 0 ||
    !Number.isInteger(value.citation.version_number) ||
    typeof value.citation.excerpt !== 'string' ||
    value.citation.excerpt.length > SEARCH_EXCERPT_MAX_LENGTH ||
    !hasSourceFields(value.citation) ||
    !isDocument(value.document)
  ) {
    return false
  }
  return (
    value.citation.chunk_id === value.chunk_id &&
    value.citation.document_id === value.document_id &&
    value.citation.document_version_id === value.document_version_id &&
    value.citation.version_number === value.version_number &&
    value.citation.document_title === value.document.filename &&
    value.citation.excerpt === value.excerpt &&
    hasSameSource(value.citation, value.source)
  )
}

function isAuthorizedSearchData(value: unknown): value is AuthorizedSearchData {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      'status',
      'query',
      'top_k',
      'result_count',
      'authorized_scope',
      'indexing',
      'evaluation_summary',
      'results',
    ]) ||
    typeof value.status !== 'string' ||
    !SEARCH_STATUSES.has(value.status) ||
    typeof value.query !== 'string' ||
    !Number.isInteger(value.top_k) ||
    (value.top_k as number) < SEARCH_TOP_K_MIN ||
    (value.top_k as number) > SEARCH_TOP_K_MAX ||
    !isNonNegativeInteger(value.result_count) ||
    !isRecord(value.authorized_scope) ||
    !hasOnlyKeys(value.authorized_scope, ['grants']) ||
    !Array.isArray(value.authorized_scope.grants) ||
    !value.authorized_scope.grants.every(isScopeGrant) ||
    !isRecord(value.indexing) ||
    !hasOnlyKeys(value.indexing, [
      'status',
      'active_chunk_count',
      'indexed_document_count',
      'embedding',
    ]) ||
    typeof value.indexing.status !== 'string' ||
    !SEARCH_STATUSES.has(value.indexing.status) ||
    !isNonNegativeInteger(value.indexing.active_chunk_count) ||
    !isNonNegativeInteger(value.indexing.indexed_document_count) ||
    !isRecord(value.indexing.embedding) ||
    !hasOnlyKeys(value.indexing.embedding, [
      'status',
      'model',
      'dimensions',
      'embedded_chunk_count',
      'pending_chunk_count',
      'failed_chunk_count',
    ]) ||
    typeof value.indexing.embedding.status !== 'string' ||
    !EMBEDDING_STATUSES.has(value.indexing.embedding.status) ||
    typeof value.indexing.embedding.model !== 'string' ||
    value.indexing.embedding.model.length === 0 ||
    !Number.isInteger(value.indexing.embedding.dimensions) ||
    (value.indexing.embedding.dimensions as number) < 1 ||
    !isNonNegativeInteger(value.indexing.embedding.embedded_chunk_count) ||
    !isNonNegativeInteger(value.indexing.embedding.pending_chunk_count) ||
    !isNonNegativeInteger(value.indexing.embedding.failed_chunk_count) ||
    !isEvaluationSummary(value.evaluation_summary) ||
    !Array.isArray(value.results) ||
    value.results.length !== value.result_count ||
    value.results.length > (value.top_k as number)
  ) {
    return false
  }
  return value.results.every(isSearchResult)
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
