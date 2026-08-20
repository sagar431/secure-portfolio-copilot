import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import * as documentApi from '../api/documents'
import { AuthContext, type AuthContextValue } from '../auth/context'
import { DocumentIngestionPage } from './DocumentIngestionPage'
import {
  documentSummary,
  ingestionOptions,
  pdfPreview,
} from '../test/documentFixtures'
import type { IngestionJobData, UploadDocumentData } from '../types/documents'

vi.mock('../api/documents', () => ({
  approveDocumentVersion: vi.fn(),
  deleteDocument: vi.fn(),
  getDocumentLibrary: vi.fn(),
  getDocumentPreview: vi.fn(),
  getIngestionOptions: vi.fn(),
  getIngestionStatus: vi.fn(),
  rejectDocumentVersion: vi.fn(),
  uploadDocument: vi.fn(),
}))

const authValue: AuthContextValue = {
  status: 'authenticated',
  currentUser: {
    identity: {
      id: 'user-nora',
      email: 'nora@example.com',
      display_name: 'Nora Admin',
    },
    active_memberships: [],
    authorization_scope: {
      grants: [
        {
          workspace: {
            id: ingestionOptions.tenants[0].id,
            slug: ingestionOptions.tenants[0].slug,
            name: ingestionOptions.tenants[0].name,
          },
          company_ids: ['company-orion'],
          company_slugs: ['orion-main'],
          query_departments: [],
          capabilities: ['MANAGE_UPLOADS'],
        },
      ],
    },
  },
  accessToken: 'signed-nora-token',
  login: vi.fn(),
  logout: vi.fn(),
}

const uploadData: UploadDocumentData = {
  job_id: 'job-1',
  document_id: documentSummary.document_id,
  version_id: documentSummary.version_id,
  version_number: 1,
  status: 'PREVIEW_READY',
  warnings: [],
  safe_error_code: null,
  page_count: documentSummary.page_count,
  sheet_count: documentSummary.sheet_count,
  row_count: documentSummary.row_count,
  cell_count: documentSummary.cell_count,
  updated_at: documentSummary.created_at,
  filename: documentSummary.filename,
  checksum: documentSummary.checksum,
  deduplicated: false,
}

function job(status: IngestionJobData['status']): IngestionJobData {
  return {
    ...uploadData,
    status,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={authValue}>
        <DocumentIngestionPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('DocumentIngestionPage', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.resetAllMocks()
    vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    vi.mocked(documentApi.getIngestionOptions).mockResolvedValue({
      data: ingestionOptions,
      request_id: 'options-request',
    })
    vi.mocked(documentApi.getDocumentLibrary).mockResolvedValue({
      data: { items: [documentSummary], total: 1, limit: 100, offset: 0 },
      request_id: 'library-request',
    })
    vi.mocked(documentApi.getDocumentPreview).mockResolvedValue({
      data: pdfPreview,
      request_id: 'preview-request',
    })
    vi.mocked(documentApi.approveDocumentVersion).mockResolvedValue({
      data: {
        document_id: documentSummary.document_id,
        version_id: documentSummary.version_id,
        status: 'APPROVED',
        current_approved_version_id: documentSummary.version_id,
      },
      request_id: 'approve-request',
    })
    vi.mocked(documentApi.rejectDocumentVersion).mockResolvedValue({
      data: {
        document_id: documentSummary.document_id,
        version_id: documentSummary.version_id,
        status: 'REJECTED',
        current_approved_version_id: null,
      },
      request_id: 'reject-request',
    })
    vi.mocked(documentApi.deleteDocument).mockResolvedValue({
      data: {
        document_id: documentSummary.document_id,
        status: 'DELETED',
      },
      request_id: 'delete-request',
    })
    vi.mocked(documentApi.uploadDocument).mockImplementation((input) => {
      input.onProgress?.(45)
      input.onProgress?.(100)
      return Promise.resolve({ data: uploadData, request_id: 'upload-request' })
    })
  })

  it('uploads trusted metadata, previews it, and enables approval only after preview', async () => {
    renderPage()

    expect(
      await screen.findByRole('heading', { name: 'Upload a document' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()

    fireEvent.change(screen.getByLabelText('Reporting period'), {
      target: { value: 'FY2025' },
    })
    const file = new File(['%PDF-safe'], 'Orion.pdf', {
      type: 'application/pdf',
    })
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [file] },
    })
    const uploadButton = screen.getByRole('button', { name: 'Upload' })
    const uploadForm = uploadButton.closest('form')
    if (!uploadForm) {
      throw new Error('Upload form was not rendered')
    }
    fireEvent.submit(uploadForm)

    expect(
      await screen.findByRole('heading', { name: 'Page 1' }),
    ).toBeInTheDocument()
    expect(documentApi.uploadDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        token: 'signed-nora-token',
        file,
        metadata: {
          tenant_id: 'tenant-orion',
          company_id: 'company-orion',
          department: 'finance',
          visibility: 'DEPARTMENT_PRIVATE',
          classification: 'FINANCE_ONLY',
          document_type: 'FINANCIAL_REPORT',
          reporting_period: 'FY2025',
        },
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() =>
      expect(documentApi.approveDocumentVersion).toHaveBeenCalledWith(
        'signed-nora-token',
        documentSummary.document_id,
        documentSummary.version_id,
      ),
    )
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
  })

  it('polls validating and parsing jobs until a preview is ready', async () => {
    vi.mocked(documentApi.uploadDocument).mockImplementation((input) => {
      input.onProgress?.(100)
      return Promise.resolve({
        data: { ...uploadData, status: 'VALIDATING' },
        request_id: 'upload-request',
      })
    })
    vi.mocked(documentApi.getIngestionStatus)
      .mockResolvedValueOnce({ data: job('PARSING'), request_id: 'parse-1' })
      .mockResolvedValueOnce({
        data: job('PREVIEW_READY'),
        request_id: 'parse-2',
      })
    renderPage()
    await screen.findByRole('heading', { name: 'Upload a document' })
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('Reporting period'), {
      target: { value: 'FY2025' },
    })
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [new File(['%PDF'], 'Orion.pdf')] },
    })
    fireEvent.submit(
      screen.getByRole('button', { name: 'Upload' }).closest('form')!,
    )

    await act(async () => vi.advanceTimersByTimeAsync(1_000))
    expect(screen.getByRole('heading', { name: 'Page 1' })).toBeInTheDocument()
    expect(documentApi.getIngestionStatus).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('shows the request ID when status polling fails', async () => {
    vi.mocked(documentApi.uploadDocument).mockResolvedValue({
      data: { ...uploadData, status: 'VALIDATING' },
      request_id: 'upload-request',
    })
    vi.mocked(documentApi.getIngestionStatus).mockRejectedValue(
      new ApiError(
        'Document parsing failed.',
        500,
        'parsing_failed',
        'poll-request-id',
      ),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Upload a document' })
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('Reporting period'), {
      target: { value: 'FY2025' },
    })
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [new File(['%PDF'], 'Orion.pdf')] },
    })
    fireEvent.submit(
      screen.getByRole('button', { name: 'Upload' }).closest('form')!,
    )

    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Document parsing failed. Request ID: poll-request-id',
    )
    vi.useRealTimers()
  })

  it('supports rejection, reports decision failures, and hides decisions outside preview-ready', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Document library' })
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByRole('button', { name: 'Reject' })
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(documentApi.rejectDocumentVersion).toHaveBeenCalled(),
    )
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()

    vi.mocked(documentApi.getDocumentPreview).mockResolvedValueOnce({
      data: pdfPreview,
      request_id: 'preview-request',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByRole('button', { name: 'Approve' })
    vi.mocked(documentApi.approveDocumentVersion).mockRejectedValueOnce(
      new ApiError('Approval denied.', 403, 'forbidden', 'approval-request'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Approval denied. Request ID: approval-request',
    )
  })

  it('applies library filters and starts an explicit locked new version', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Document library' })
    fireEvent.change(
      screen.getByLabelText('Department', {
        selector: '.library-filters select',
      }),
      {
        target: { value: 'shared' },
      },
    )
    fireEvent.change(
      screen.getByLabelText('Document type', {
        selector: '.library-filters select',
      }),
      {
        target: { value: 'OTHER' },
      },
    )
    fireEvent.change(screen.getByLabelText('Status'), {
      target: { value: 'APPROVED' },
    })
    await waitFor(() =>
      expect(documentApi.getDocumentLibrary).toHaveBeenLastCalledWith(
        'signed-nora-token',
        expect.objectContaining({
          department: 'shared',
          document_type: 'OTHER',
          status: 'APPROVED',
          offset: 0,
        }),
        expect.any(AbortSignal),
      ),
    )

    fireEvent.click(screen.getByRole('button', { name: 'New version' }))
    expect(
      await screen.findByRole('heading', { name: 'Upload version 2' }),
    ).toBeInTheDocument()
    const uploadSection = screen
      .getByRole('heading', { name: 'Upload version 2' })
      .closest('section')
    if (!uploadSection) {
      throw new Error('New-version form was not rendered')
    }
    expect(within(uploadSection).getByLabelText('Tenant')).toBeDisabled()
    expect(within(uploadSection).getByLabelText('Classification')).toHaveValue(
      'FINANCE_ONLY',
    )
    const versionFile = new File(['%PDF-version-2'], 'Orion-v2.pdf', {
      type: 'application/pdf',
    })
    fireEvent.change(within(uploadSection).getByLabelText('File'), {
      target: { files: [versionFile] },
    })
    fireEvent.submit(
      within(uploadSection)
        .getByRole('button', { name: 'Upload new version' })
        .closest('form')!,
    )
    await waitFor(() => expect(documentApi.uploadDocument).toHaveBeenCalled())
    const versionUpload = vi
      .mocked(documentApi.uploadDocument)
      .mock.calls.at(-1)?.[0]
    expect(versionUpload?.documentId).toBe(documentSummary.document_id)
    expect(versionUpload?.file).toBe(versionFile)
    expect(versionUpload?.metadata).toMatchObject({
      classification: 'FINANCE_ONLY',
      visibility: 'DEPARTMENT_PRIVATE',
    })
  })

  it('requires confirmation before deleting a manageable document', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Document library' })

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(
      screen.getByRole('dialog', { name: 'Delete this document?' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent(
      `${documentSummary.filename}, currently at version ${documentSummary.version_number}`,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(documentApi.deleteDocument).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete document' }))

    await waitFor(() =>
      expect(documentApi.deleteDocument).toHaveBeenCalledWith(
        'signed-nora-token',
        documentSummary.document_id,
      ),
    )
    expect(
      await screen.findByText(
        'Document deleted and made unavailable immediately.',
      ),
    ).toBeInTheDocument()
  })

  it('shows a safe upload error and request ID', async () => {
    vi.mocked(documentApi.uploadDocument).mockRejectedValueOnce(
      new ApiError(
        'The uploaded file is invalid.',
        422,
        'invalid_file_signature',
        'upload-denied',
      ),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Upload a document' })
    fireEvent.change(screen.getByLabelText('Reporting period'), {
      target: { value: 'FY2025' },
    })
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [new File(['fake'], 'fake.pdf')] },
    })
    const uploadButton = screen.getByRole('button', { name: 'Upload' })
    const uploadForm = uploadButton.closest('form')
    if (!uploadForm) {
      throw new Error('Upload form was not rendered')
    }
    fireEvent.submit(uploadForm)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The uploaded file is invalid. Request ID: upload-denied',
    )
  })
})
