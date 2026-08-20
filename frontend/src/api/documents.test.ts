import { describe, expect, it, vi } from 'vitest'

import {
  getDocumentPreview,
  getIngestionOptions,
  uploadDocument,
} from './documents'
import { ApiError } from './client'
import type {
  ApiUploadResultData,
  UploadDocumentData,
  UploadMetadata,
} from '../types/documents'

class FakeXMLHttpRequest {
  static latest: FakeXMLHttpRequest | null = null

  readonly upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  }
  method = ''
  url = ''
  requestHeaders = new Map<string, string>()
  requestBody: Document | XMLHttpRequestBodyInit | null = null
  response: unknown = null
  responseText = ''
  responseType: XMLHttpRequestResponseType = ''
  status = 0
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeXMLHttpRequest.latest = this
  }

  open(method: string, url: string) {
    this.method = method
    this.url = url
  }

  setRequestHeader(name: string, value: string) {
    this.requestHeaders.set(name, value)
  }

  getResponseHeader(name: string) {
    return name.toLowerCase() === 'x-request-id' ? 'header-request-id' : null
  }

  send(body: Document | XMLHttpRequestBodyInit | null) {
    this.requestBody = body
  }

  abort() {
    this.onabort?.()
  }

  progress(loaded: number, total: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded,
      total,
    } as ProgressEvent)
  }

  respond(status: number, body: unknown) {
    this.status = status
    this.response = body
    this.responseText = JSON.stringify(body)
    this.onload?.()
  }
}

const metadata: UploadMetadata = {
  tenant_id: 'tenant-orion',
  company_id: 'company-orion',
  department: 'finance',
  visibility: 'DEPARTMENT_PRIVATE',
  classification: 'FINANCE_ONLY',
  document_type: 'FINANCIAL_REPORT',
  reporting_period: 'FY2025',
}

const uploadData: UploadDocumentData = {
  job_id: 'job-1',
  document_id: 'document-1',
  version_id: 'version-1',
  version_number: 1,
  status: 'PREVIEW_READY',
  warnings: [],
  safe_error_code: null,
  page_count: 1,
  sheet_count: 0,
  row_count: 0,
  cell_count: 0,
  updated_at: '2026-08-21T10:00:01Z',
  filename: 'Orion.pdf',
  checksum: 'checksum',
  deduplicated: false,
}

const backendUploadData: ApiUploadResultData = {
  document: {
    id: 'document-1',
    scope: {
      tenant_id: 'tenant-orion',
      tenant_slug: 'orion',
      tenant_name: 'Orion Capital',
      company_id: 'company-orion',
      company_slug: 'orion-main',
      company_name: 'Orion Portfolio Company',
      department: 'finance',
      visibility: 'DEPARTMENT_PRIVATE',
      classification: 'FINANCE_ONLY',
    },
    document_type: 'FINANCIAL_REPORT',
    reporting_period: 'FY2025',
    current_approved_version_id: null,
    version: {
      id: 'version-1',
      version_number: 1,
      original_filename: 'Orion.pdf',
      media_type: 'application/pdf',
      source_type: 'PDF',
      checksum_sha256: 'checksum',
      size_bytes: 9,
      status: 'PREVIEW_READY',
      page_count: 1,
      sheet_count: 0,
      row_count: 0,
      cell_count: 0,
      warnings: [],
      uploaded_by_user_id: 'user-nora',
      approved_by_user_id: null,
      created_at: '2026-08-21T10:00:01Z',
    },
    ingestion_job_id: 'job-1',
  },
  deduplicated: false,
}

describe('uploadDocument', () => {
  it('sends metadata and file as multipart with progress and idempotency', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest)
    const onProgress = vi.fn()
    const file = new File(['%PDF-safe'], 'Orion.pdf', {
      type: 'application/pdf',
    })

    const promise = uploadDocument({
      token: 'signed-token',
      metadata,
      file,
      idempotencyKey: 'idempotency-1',
      onProgress,
    })
    const xhr = FakeXMLHttpRequest.latest
    expect(xhr).not.toBeNull()
    if (!xhr) {
      throw new Error('XHR was not created')
    }
    xhr.progress(5, 10)
    xhr.respond(201, { data: backendUploadData, request_id: 'upload-request' })

    await expect(promise).resolves.toEqual({
      data: uploadData,
      request_id: 'upload-request',
    })
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toContain('/api/admin/documents')
    expect(xhr.requestHeaders.get('Authorization')).toBe('Bearer signed-token')
    expect(xhr.requestHeaders.get('Idempotency-Key')).toBe('idempotency-1')
    expect(xhr.requestHeaders.has('Content-Type')).toBe(false)
    expect(onProgress).toHaveBeenCalledWith(50)
    expect(xhr.requestBody).toBeInstanceOf(FormData)
    if (!(xhr.requestBody instanceof FormData)) {
      throw new Error('Multipart body was not created')
    }
    const form = xhr.requestBody
    const metadataEntry = form.get('metadata')
    if (typeof metadataEntry !== 'string') {
      throw new Error('Metadata was not serialized')
    }
    expect(JSON.parse(metadataEntry)).toEqual(metadata)
    expect(form.get('file')).toBe(file)
  })

  it('converts a safe backend error envelope into ApiError', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest)
    const promise = uploadDocument({
      token: 'signed-token',
      metadata,
      file: new File(['fake'], 'fake.pdf'),
      idempotencyKey: 'idempotency-2',
    })
    const xhr = FakeXMLHttpRequest.latest
    if (!xhr) {
      throw new Error('XHR was not created')
    }
    xhr.respond(422, {
      error: {
        code: 'invalid_file_signature',
        message: 'The uploaded file is invalid.',
      },
      request_id: 'upload-denied',
    })

    await expect(promise).rejects.toEqual(
      new ApiError(
        'The uploaded file is invalid.',
        422,
        'invalid_file_signature',
        'upload-denied',
      ),
    )
  })
})

describe('document read APIs', () => {
  it('maps the nested backend preview DTO into bounded-renderer data', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: {
              document: backendUploadData.document,
              pages: [{ page_number: 1, text: 'Trusted preview text.' }],
              sheets: [],
            },
            request_id: 'preview-request',
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    await expect(
      getDocumentPreview('signed-token', 'document-1', 'version-1'),
    ).resolves.toMatchObject({
      request_id: 'preview-request',
      data: {
        document: {
          document_id: 'document-1',
          version_id: 'version-1',
          classification: 'FINANCE_ONLY',
        },
        content: {
          kind: 'pdf',
          pages: [{ page_number: 1, text: 'Trusted preview text.' }],
        },
      },
    })
  })

  it('preserves safe expired-session errors and request IDs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'invalid_token',
              message: 'Authentication is required.',
            },
            request_id: 'expired-session-request',
          }),
          {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    )

    await expect(getIngestionOptions('expired-token')).rejects.toEqual(
      new ApiError(
        'Authentication is required.',
        401,
        'invalid_token',
        'expired-session-request',
      ),
    )
  })
})
