import type {
  DocumentClassification,
  DocumentSourceType,
  DocumentType,
  DocumentVisibility,
} from './documents'

export const SEARCH_QUERY_MAX_LENGTH = 500
export const SEARCH_EXCERPT_MAX_LENGTH = 500
export const SEARCH_TOP_K_MIN = 1
export const SEARCH_TOP_K_MAX = 20
export const SEARCH_TOP_K_DEFAULT = 5

export interface AuthorizedSearchRequest {
  query: string
  top_k: number
}

export interface SearchScopeGrantData {
  workspace: {
    id: string
    slug: string
    name: string
  }
  company_ids: string[]
  company_slugs: string[]
  query_departments: string[]
}

export interface SearchIndexingData {
  status: 'ready' | 'indexing'
  active_chunk_count: number
  indexed_document_count: number
}

export interface SearchSourceData {
  page_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  cell_start: string | null
  cell_end: string | null
}

export interface SearchDocumentData {
  filename: string
  source_type: DocumentSourceType
  document_type: DocumentType
  reporting_period: string | null
  tenant_slug: string
  company_slug: string
  department: string
  visibility: DocumentVisibility
  classification: DocumentClassification
}

export interface AuthorizedSearchResultData {
  chunk_id: string
  document_id: string
  document_version_id: string
  version_number: number
  excerpt: string
  score: number
  source: SearchSourceData
  document: SearchDocumentData
}

export interface AuthorizedSearchData {
  status: 'ready' | 'indexing'
  query: string
  top_k: number
  result_count: number
  authorized_scope: {
    grants: SearchScopeGrantData[]
  }
  indexing: SearchIndexingData
  results: AuthorizedSearchResultData[]
}
