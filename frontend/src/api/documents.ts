import {
  ApiError,
  apiUrl,
  isErrorEnvelope,
  isSuccessEnvelope,
  requestJson,
} from './client'
import type { ApiSuccessEnvelope } from '../types/api'
import type {
  ApiDocumentData,
  ApiDocumentListData,
  ApiDocumentPreviewData,
  ApiIngestionStatusData,
  ApiUploadResultData,
  ApiVersionActionData,
  DeleteDocumentData,
  DocumentFilters,
  DocumentLibraryData,
  DocumentMutationData,
  DocumentPreviewData,
  IngestionJobData,
  IngestionOptionsData,
  UploadDocumentData,
  UploadMetadata,
} from '../types/documents'

function mapEnvelope<Source, Target>(
  envelope: ApiSuccessEnvelope<Source>,
  transform: (data: Source) => Target,
): ApiSuccessEnvelope<Target> {
  return { data: transform(envelope.data), request_id: envelope.request_id }
}

function warningMessages(warnings: { message: string }[]) {
  return warnings.map((warning) => warning.message)
}

function toDocumentSummary(document: ApiDocumentData) {
  const { scope, version } = document
  return {
    document_id: document.id,
    version_id: version.id,
    version_number: version.version_number,
    filename: version.original_filename,
    checksum: version.checksum_sha256,
    source_type: version.source_type,
    detected_mime_type: version.media_type,
    size_bytes: version.size_bytes,
    tenant: {
      id: scope.tenant_id,
      slug: scope.tenant_slug,
      name: scope.tenant_name,
    },
    company: {
      id: scope.company_id,
      slug: scope.company_slug,
      name: scope.company_name,
    },
    department: scope.department,
    visibility: scope.visibility,
    classification: scope.classification,
    document_type: document.document_type,
    reporting_period: document.reporting_period,
    status: version.status,
    page_count: version.page_count,
    sheet_count: version.sheet_count,
    row_count: version.row_count,
    cell_count: version.cell_count,
    uploader_id: version.uploaded_by_user_id,
    approved_by_user_id: version.approved_by_user_id,
    current_approved_version_id: document.current_approved_version_id,
    warnings: warningMessages(version.warnings),
    created_at: version.created_at,
    ingestion_job_id: document.ingestion_job_id,
  }
}

function toIngestionJob(data: ApiIngestionStatusData): IngestionJobData {
  return {
    job_id: data.ingestion_job_id,
    document_id: data.document_id,
    version_id: data.document_version_id,
    version_number: data.version_number,
    status: data.status,
    warnings: warningMessages(data.warnings),
    safe_error_code: data.safe_error_code,
    page_count: data.page_count,
    sheet_count: data.sheet_count,
    row_count: data.row_count,
    cell_count: data.cell_count,
    updated_at: data.updated_at,
  }
}

function toUploadDocument(data: ApiUploadResultData): UploadDocumentData {
  const document = toDocumentSummary(data.document)
  return {
    job_id: data.document.ingestion_job_id,
    document_id: document.document_id,
    version_id: document.version_id,
    version_number: document.version_number,
    status: document.status,
    warnings: document.warnings,
    safe_error_code: null,
    page_count: document.page_count,
    sheet_count: document.sheet_count,
    row_count: document.row_count,
    cell_count: document.cell_count,
    updated_at: document.created_at,
    filename: document.filename,
    checksum: document.checksum,
    deduplicated: data.deduplicated,
  }
}

export function getIngestionOptions(token: string, signal?: AbortSignal) {
  return requestJson<IngestionOptionsData>('/api/admin/ingestion/options', {
    token,
    signal,
  })
}

function documentQuery(filters: DocumentFilters) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') {
      query.set(key, String(value))
    }
  }
  const suffix = query.toString()
  return suffix ? `?${suffix}` : ''
}

export function getDocumentLibrary(
  token: string,
  filters: DocumentFilters = {},
  signal?: AbortSignal,
) {
  return requestJson<ApiDocumentListData>(
    `/api/admin/documents${documentQuery(filters)}`,
    { token, signal },
  ).then((response) =>
    mapEnvelope(response, (data): DocumentLibraryData => ({
      ...data,
      items: data.items.map(toDocumentSummary),
    })),
  )
}

export function getIngestionStatus(
  token: string,
  jobId: string,
  signal?: AbortSignal,
) {
  return requestJson<ApiIngestionStatusData>(`/api/admin/ingestion/${jobId}`, {
    token,
    signal,
  }).then((response) => mapEnvelope(response, toIngestionJob))
}

export function getDocumentPreview(
  token: string,
  documentId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return requestJson<ApiDocumentPreviewData>(
    `/api/admin/documents/${documentId}/versions/${versionId}/preview`,
    { token, signal },
  ).then((response) =>
    mapEnvelope(response, (data): DocumentPreviewData => {
      const document = toDocumentSummary(data.document)
      if (document.source_type === 'PDF') {
        return {
          document,
          warnings: document.warnings,
          content: {
            kind: 'pdf',
            page_count: document.page_count,
            pages: data.pages,
          },
        }
      }
      if (document.source_type !== 'XLSX' && document.source_type !== 'CSV') {
        throw new ApiError(
          'Backend returned an invalid response.',
          200,
          'invalid_response',
          response.request_id,
        )
      }
      return {
        document,
        warnings: document.warnings,
        content: {
          kind: 'spreadsheet',
          source_type: document.source_type,
          sheet_count: document.sheet_count,
          sheets: data.sheets.map((sheet) => ({
            sheet_index: sheet.sheet_index,
            sheet_name: sheet.name,
            row_count: sheet.row_count,
            column_count: sheet.column_count,
            rows: sheet.rows.map((row) => ({
              row_number: row.row_number,
              cells: row.cells.map((cell) => ({
                coordinate: cell.coordinate,
                value: cell.value,
                value_kind: cell.value_kind,
                formula_like: cell.formula_like,
              })),
            })),
          })),
        },
      }
    }),
  )
}

function toMutation(data: ApiVersionActionData): DocumentMutationData {
  return {
    document_id: data.document_id,
    version_id: data.document_version_id,
    status: data.status,
    current_approved_version_id: data.current_approved_version_id,
  }
}

export function approveDocumentVersion(
  token: string,
  documentId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return requestJson<ApiVersionActionData>(
    `/api/admin/documents/${documentId}/versions/${versionId}/approve`,
    { method: 'POST', token, signal },
  ).then((response) => mapEnvelope(response, toMutation))
}

export function rejectDocumentVersion(
  token: string,
  documentId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return requestJson<ApiVersionActionData>(
    `/api/admin/documents/${documentId}/versions/${versionId}/reject`,
    {
      method: 'POST',
      token,
      signal,
    },
  ).then((response) => mapEnvelope(response, toMutation))
}

export function deleteDocument(
  token: string,
  documentId: string,
  signal?: AbortSignal,
) {
  return requestJson<DeleteDocumentData>(`/api/admin/documents/${documentId}`, {
    method: 'DELETE',
    token,
    signal,
  })
}

interface UploadDocumentInput {
  token: string
  metadata: UploadMetadata
  file: File
  idempotencyKey: string
  documentId?: string
  signal?: AbortSignal
  onProgress?: (percentage: number) => void
}

function parseXhrBody(xhr: XMLHttpRequest): unknown {
  if (xhr.response && typeof xhr.response === 'object') {
    return xhr.response
  }
  if (xhr.responseType === 'json') {
    return null
  }
  if (!xhr.responseText) {
    return null
  }
  try {
    return JSON.parse(xhr.responseText) as unknown
  } catch {
    return null
  }
}

export function uploadDocument({
  token,
  metadata,
  file,
  idempotencyKey,
  documentId,
  signal,
  onProgress,
}: UploadDocumentInput): Promise<ApiSuccessEnvelope<UploadDocumentData>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const path = documentId
      ? `/api/admin/documents/${documentId}/versions`
      : '/api/admin/documents'
    const removeAbortListener = () =>
      signal?.removeEventListener('abort', abort)
    const settle = (callback: () => void) => {
      removeAbortListener()
      callback()
    }
    const abort = () => xhr.abort()

    xhr.open('POST', apiUrl(path))
    xhr.responseType = 'json'
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Idempotency-Key', idempotencyKey)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.(
          Math.min(100, Math.round((event.loaded / event.total) * 100)),
        )
      }
    }
    xhr.onerror = () =>
      settle(() =>
        reject(
          new ApiError(
            'Unable to reach the backend.',
            0,
            'network_error',
            null,
          ),
        ),
      )
    xhr.onabort = () =>
      settle(() => reject(new DOMException('Upload aborted.', 'AbortError')))
    xhr.onload = () => {
      const body = parseXhrBody(xhr)
      const requestId = xhr.getResponseHeader('X-Request-ID')
      if (xhr.status < 200 || xhr.status >= 300) {
        settle(() => {
          if (isErrorEnvelope(body)) {
            reject(
              new ApiError(
                body.error.message,
                xhr.status,
                body.error.code,
                body.request_id,
              ),
            )
            return
          }
          reject(
            new ApiError(
              'Backend request failed.',
              xhr.status,
              'request_failed',
              requestId,
            ),
          )
        })
        return
      }
      settle(() => {
        if (isSuccessEnvelope<ApiUploadResultData>(body)) {
          resolve(mapEnvelope(body, toUploadDocument))
          return
        }
        reject(
          new ApiError(
            'Backend returned an invalid response.',
            xhr.status,
            'invalid_response',
            requestId,
          ),
        )
      })
    }

    if (signal?.aborted) {
      xhr.abort()
      return
    }
    signal?.addEventListener('abort', abort, { once: true })

    const form = new FormData()
    form.append('metadata', JSON.stringify(metadata))
    form.append('file', file)
    xhr.send(form)
  })
}
