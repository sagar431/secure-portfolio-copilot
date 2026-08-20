export type IngestionStatus =
  | 'UPLOADED'
  | 'VALIDATING'
  | 'PARSING'
  | 'PREVIEW_READY'
  | 'APPROVED'
  | 'REJECTED'
  | 'VALIDATION_FAILED'
  | 'PARSING_FAILED'
  | 'DELETED'

export type DocumentVisibility = 'DEPARTMENT_PRIVATE' | 'TENANT_SHARED'

export type DocumentClassification =
  'FINANCE_ONLY' | 'LEGAL_ONLY_CONFIDENTIAL' | 'TENANT_SHARED'

export type DocumentType =
  | 'FINANCIAL_REPORT'
  | 'LEGAL_AGREEMENT'
  | 'POLICY'
  | 'EMAIL'
  | 'SPREADSHEET'
  | 'OTHER'

export type DocumentSourceType = 'PDF' | 'XLSX' | 'CSV' | 'UNKNOWN'

export interface CompanyOption {
  id: string
  slug: string
  name: string
}

export interface TenantOption {
  id: string
  slug: string
  name: string
  companies: CompanyOption[]
}

export interface ClassificationPairOption {
  department: string
  visibility: DocumentVisibility
  classification: DocumentClassification
  label: string
}

export interface DocumentTypeOption {
  value: DocumentType
  label: string
  reporting_period_required: boolean
}

export interface IngestionOptionsData {
  tenants: TenantOption[]
  classification_pairs: ClassificationPairOption[]
  document_types: DocumentTypeOption[]
  limits: {
    max_upload_bytes: number
    extensions: string[]
    mime_types: string[]
  }
}

export interface UploadMetadata {
  tenant_id: string
  company_id: string
  department: string
  visibility: DocumentVisibility
  classification: DocumentClassification
  document_type: DocumentType
  reporting_period: string | null
}

export interface WarningData {
  code: string
  message: string
}

export interface ApiDocumentScopeData {
  tenant_id: string
  tenant_slug: string
  tenant_name: string
  company_id: string
  company_slug: string
  company_name: string
  department: string
  visibility: DocumentVisibility
  classification: DocumentClassification
}

export interface ApiDocumentVersionData {
  id: string
  version_number: number
  original_filename: string
  media_type: string
  source_type: DocumentSourceType
  checksum_sha256: string
  size_bytes: number
  status: IngestionStatus
  page_count: number
  sheet_count: number
  row_count: number
  cell_count: number
  warnings: WarningData[]
  uploaded_by_user_id: string
  approved_by_user_id: string | null
  created_at: string
}

export interface ApiDocumentData {
  id: string
  scope: ApiDocumentScopeData
  document_type: DocumentType
  reporting_period: string | null
  current_approved_version_id: string | null
  version: ApiDocumentVersionData
  ingestion_job_id: string
}

export interface ApiUploadResultData {
  document: ApiDocumentData
  deduplicated: boolean
}

export interface ApiIngestionStatusData {
  ingestion_job_id: string
  document_id: string
  document_version_id: string
  version_number: number
  status: IngestionStatus
  safe_error_code: string | null
  warnings: WarningData[]
  page_count: number
  sheet_count: number
  row_count: number
  cell_count: number
  started_at: string | null
  completed_at: string | null
  updated_at: string
}

export interface ApiParsedPageData {
  page_number: number
  text: string
}

export interface ApiParsedCellData {
  row_number: number
  column_number: number
  coordinate: string
  value: string
  value_kind: string
  formula_like: boolean
}

export interface ApiParsedRowData {
  row_number: number
  cells: ApiParsedCellData[]
}

export interface ApiParsedSheetData {
  sheet_index: number
  name: string
  row_count: number
  column_count: number
  rows: ApiParsedRowData[]
}

export interface ApiDocumentPreviewData {
  document: ApiDocumentData
  pages: ApiParsedPageData[]
  sheets: ApiParsedSheetData[]
}

export interface ApiVersionActionData {
  document_id: string
  document_version_id: string
  status: IngestionStatus
  current_approved_version_id: string | null
}

export interface ApiDocumentListData {
  items: ApiDocumentData[]
  total: number
  limit: number
  offset: number
}

export interface IngestionJobData {
  job_id: string
  document_id: string
  version_id: string
  version_number: number
  status: IngestionStatus
  warnings: string[]
  safe_error_code: string | null
  page_count: number
  sheet_count: number
  row_count: number
  cell_count: number
  updated_at: string
}

export interface UploadDocumentData extends IngestionJobData {
  filename: string
  checksum: string
  deduplicated: boolean
}

export interface DocumentSummary {
  document_id: string
  version_id: string
  version_number: number
  filename: string
  checksum: string
  source_type: DocumentSourceType
  detected_mime_type: string
  size_bytes: number
  tenant: Omit<TenantOption, 'companies'>
  company: CompanyOption
  department: string
  visibility: DocumentVisibility
  classification: DocumentClassification
  document_type: DocumentType
  reporting_period: string | null
  status: IngestionStatus
  page_count: number
  sheet_count: number
  row_count: number
  cell_count: number
  uploader_id: string
  approved_by_user_id: string | null
  current_approved_version_id: string | null
  warnings: string[]
  created_at: string
  ingestion_job_id: string
}

export interface DocumentLibraryData {
  items: DocumentSummary[]
  total: number
  limit: number
  offset: number
}

export interface ParsedPageData {
  page_number: number
  text: string
}

export interface ParsedCellData {
  coordinate: string
  value: string
  value_kind: string
  formula_like: boolean
}

export interface ParsedRowData {
  row_number: number
  cells: ParsedCellData[]
}

export interface ParsedSheetData {
  sheet_index: number
  sheet_name: string
  row_count: number
  column_count: number
  rows: ParsedRowData[]
}

export interface PdfPreviewContent {
  kind: 'pdf'
  page_count: number
  pages: ParsedPageData[]
}

export interface SpreadsheetPreviewContent {
  kind: 'spreadsheet'
  source_type: 'XLSX' | 'CSV'
  sheet_count: number
  sheets: ParsedSheetData[]
}

export interface DocumentPreviewData {
  document: DocumentSummary
  warnings: string[]
  content: PdfPreviewContent | SpreadsheetPreviewContent
}

export interface DocumentMutationData {
  document_id: string
  version_id: string
  status: IngestionStatus
  current_approved_version_id: string | null
}

export interface DeleteDocumentData {
  document_id: string
  status: 'DELETED'
}

export interface DocumentFilters {
  tenant_id?: string
  company_id?: string
  department?: string
  document_type?: DocumentType
  status?: IngestionStatus
  offset?: number
  limit?: number
}
