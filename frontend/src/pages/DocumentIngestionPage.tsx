import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  approveDocumentVersion,
  deleteDocument,
  getDocumentLibrary,
  getDocumentPreview,
  getIngestionOptions,
  getIngestionStatus,
  rejectDocumentVersion,
  uploadDocument,
} from '../api/documents'
import { useAuth } from '../auth/useAuth'
import { DeleteDocumentDialog } from '../components/DeleteDocumentDialog'
import { DocumentLibrary } from '../components/DocumentLibrary'
import { DocumentPreview } from '../components/DocumentPreview'
import {
  DocumentUploadForm,
  type UploadPhase,
  type UploadSubmission,
} from '../components/DocumentUploadForm'
import { IngestionStatusBadge } from '../components/IngestionStatusBadge'
import type {
  DocumentFilters,
  DocumentPreviewData,
  DocumentSummary,
  IngestionJobData,
  IngestionOptionsData,
  IngestionStatus,
} from '../types/documents'

const TERMINAL_JOB_STATES = new Set<IngestionStatus>([
  'PREVIEW_READY',
  'APPROVED',
  'REJECTED',
  'VALIDATION_FAILED',
  'PARSING_FAILED',
  'DELETED',
])
const MAX_STATUS_POLLS = 120
const STATUS_POLL_DELAY_MS = 500

interface SelectedVersion {
  documentId: string
  versionId: string
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function safeError(error: unknown) {
  if (error instanceof ApiError) {
    return error.requestId
      ? `${error.message} Request ID: ${error.requestId}`
      : error.message
  }
  return 'The request could not be completed. Please try again.'
}

function wait(delay: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timeoutId)
      reject(new DOMException('Request aborted.', 'AbortError'))
    }
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, delay)
    signal.addEventListener('abort', abort, { once: true })
  })
}

export function DocumentIngestionPage() {
  const auth = useAuth()
  const token = auth.accessToken
  const [options, setOptions] = useState<IngestionOptionsData | null>(null)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [filters, setFilters] = useState<DocumentFilters>({ limit: 100 })
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [libraryPage, setLibraryPage] = useState({
    total: 0,
    limit: 100,
    offset: 0,
  })
  const [libraryLoading, setLibraryLoading] = useState(true)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [libraryRefresh, setLibraryRefresh] = useState(0)
  const [selected, setSelected] = useState<SelectedVersion | null>(null)
  const [preview, setPreview] = useState<DocumentPreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [versionTarget, setVersionTarget] = useState<DocumentSummary | null>(
    null,
  )
  const [deleteTarget, setDeleteTarget] = useState<DocumentSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [decisionPending, setDecisionPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>('idle')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadJob, setUploadJob] = useState<IngestionJobData | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const uploadController = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!token) {
      return
    }
    const controller = new AbortController()
    void getIngestionOptions(token, controller.signal)
      .then((response) => setOptions(response.data))
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setOptionsError(safeError(error))
        }
      })
    return () => controller.abort()
  }, [token])

  useEffect(() => {
    if (!token) {
      return
    }
    const controller = new AbortController()
    setLibraryLoading(true)
    setLibraryError(null)
    void getDocumentLibrary(token, filters, controller.signal)
      .then((response) => {
        setDocuments(response.data.items)
        setLibraryPage({
          total: response.data.total,
          limit: response.data.limit,
          offset: response.data.offset,
        })
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setLibraryError(safeError(error))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLibraryLoading(false)
        }
      })
    return () => controller.abort()
  }, [filters, libraryRefresh, token])

  useEffect(() => {
    if (!token || !selected) {
      setPreview(null)
      return
    }
    const controller = new AbortController()
    setPreview(null)
    setPreviewError(null)
    setPreviewLoading(true)
    void getDocumentPreview(
      token,
      selected.documentId,
      selected.versionId,
      controller.signal,
    )
      .then((response) => setPreview(response.data))
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setPreviewError(safeError(error))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setPreviewLoading(false)
        }
      })
    return () => controller.abort()
  }, [selected, token])

  useEffect(
    () => () => {
      uploadController.current?.abort()
    },
    [],
  )

  const refreshLibrary = useCallback(
    () => setLibraryRefresh((value) => value + 1),
    [],
  )

  async function pollJob(
    initialJob: IngestionJobData,
    controller: AbortController,
  ) {
    if (!token) {
      return initialJob
    }
    let job = initialJob
    for (let attempt = 0; attempt < MAX_STATUS_POLLS; attempt += 1) {
      if (TERMINAL_JOB_STATES.has(job.status)) {
        return job
      }
      await wait(STATUS_POLL_DELAY_MS, controller.signal)
      const response = await getIngestionStatus(
        token,
        job.job_id,
        controller.signal,
      )
      job = response.data
      setUploadJob(job)
    }
    throw new ApiError(
      'Document processing is taking longer than expected. Check the library for its latest status.',
      408,
      'status_timeout',
      null,
    )
  }

  async function submitUpload(submission: UploadSubmission) {
    if (!token) {
      return
    }
    uploadController.current?.abort()
    const controller = new AbortController()
    uploadController.current = controller
    setUploadError(null)
    setActionMessage(null)
    setUploadJob(null)
    setUploadProgress(0)
    setUploadPhase('uploading')
    try {
      const response = await uploadDocument({
        token,
        ...submission,
        idempotencyKey: crypto.randomUUID(),
        signal: controller.signal,
        onProgress: (percentage) => {
          setUploadProgress(percentage)
          if (percentage >= 100) {
            setUploadPhase('processing')
          }
        },
      })
      setUploadProgress(100)
      setUploadPhase('processing')
      setUploadJob(response.data)
      const job = await pollJob(response.data, controller)
      setUploadJob(job)
      refreshLibrary()
      if (job.status === 'PREVIEW_READY') {
        setSelected({
          documentId: job.document_id,
          versionId: job.version_id,
        })
        setVersionTarget(null)
        setUploadPhase('complete')
        setActionMessage(
          'Upload parsed successfully. Review the preview before approval.',
        )
        return
      }
      setUploadPhase('error')
      setUploadError(
        job.safe_error_code
          ? `Document processing failed safely (${job.safe_error_code}).`
          : `Document processing ended in ${job.status.toLowerCase().replaceAll('_', ' ')}.`,
      )
    } catch (error: unknown) {
      if (isAbortError(error)) {
        setUploadPhase('idle')
        setUploadProgress(0)
        return
      }
      setUploadPhase('error')
      setUploadError(safeError(error))
    } finally {
      if (uploadController.current === controller) {
        uploadController.current = null
      }
    }
  }

  async function decide(action: 'approve' | 'reject') {
    if (!token || !preview || preview.document.status !== 'PREVIEW_READY') {
      return
    }
    setDecisionPending(true)
    setActionError(null)
    setActionMessage(null)
    try {
      const response =
        action === 'approve'
          ? await approveDocumentVersion(
              token,
              preview.document.document_id,
              preview.document.version_id,
            )
          : await rejectDocumentVersion(
              token,
              preview.document.document_id,
              preview.document.version_id,
            )
      setActionMessage(
        action === 'approve'
          ? 'Document version approved.'
          : 'Document version rejected.',
      )
      setPreview((current) =>
        current
          ? {
              ...current,
              document: { ...current.document, status: response.data.status },
            }
          : current,
      )
      refreshLibrary()
    } catch (error: unknown) {
      setActionError(safeError(error))
    } finally {
      setDecisionPending(false)
    }
  }

  async function confirmDelete(document: DocumentSummary) {
    if (!token) {
      return
    }
    setDeleting(true)
    setActionError(null)
    setActionMessage(null)
    try {
      await deleteDocument(token, document.document_id)
      if (selected?.documentId === document.document_id) {
        setSelected(null)
        setPreview(null)
      }
      setDeleteTarget(null)
      setActionMessage('Document deleted and made unavailable immediately.')
      refreshLibrary()
    } catch (error: unknown) {
      setActionError(safeError(error))
    } finally {
      setDeleting(false)
    }
  }

  if (!token) {
    return <p role="status">Preparing your authorized session…</p>
  }

  return (
    <section className="ingestion-page" aria-labelledby="ingestion-page-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h1 id="ingestion-page-title">Document ingestion</h1>
          <p className="hero-copy">
            Upload synthetic portfolio documents into trusted tenant and company
            scopes. Backend policy revalidates every action.
          </p>
        </div>
        <aside className="security-note">
          <strong>Approval gate</strong>
          <span>No document can be approved before a successful preview.</span>
        </aside>
      </header>

      {optionsError ? <p role="alert">{optionsError}</p> : null}
      {!options && !optionsError ? (
        <p role="status">Loading trusted options…</p>
      ) : null}
      {options?.tenants.length ? (
        <DocumentUploadForm
          key={versionTarget?.version_id ?? 'new-document'}
          options={options}
          targetDocument={versionTarget}
          phase={uploadPhase}
          progress={uploadProgress}
          onSubmit={(submission) => void submitUpload(submission)}
          onCancelUpload={() => uploadController.current?.abort()}
          onCancelVersion={() => setVersionTarget(null)}
        />
      ) : options ? (
        <p className="empty-state">You have no manageable upload scopes.</p>
      ) : null}

      {uploadJob ? (
        <section className="job-status" aria-labelledby="job-status-title">
          <h2 id="job-status-title">Current ingestion status</h2>
          <IngestionStatusBadge status={uploadJob.status} />
          {uploadJob.warnings.length ? (
            <ul>
              {uploadJob.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {uploadError ? <p role="alert">{uploadError}</p> : null}
      {actionError ? <p role="alert">{actionError}</p> : null}
      {actionMessage ? <p role="status">{actionMessage}</p> : null}

      {options ? (
        <DocumentLibrary
          documents={documents}
          total={libraryPage.total}
          limit={libraryPage.limit}
          offset={libraryPage.offset}
          options={options}
          filters={filters}
          loading={libraryLoading}
          selectedVersionId={selected?.versionId ?? null}
          onFiltersChange={setFilters}
          onSelect={(document) =>
            setSelected({
              documentId: document.document_id,
              versionId: document.version_id,
            })
          }
          onNewVersion={(document) => {
            setVersionTarget(document)
            setUploadPhase('idle')
            setUploadError(null)
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }}
          onDelete={setDeleteTarget}
        />
      ) : null}
      {libraryError ? <p role="alert">{libraryError}</p> : null}

      {previewLoading ? <p role="status">Loading parsed preview…</p> : null}
      {previewError ? <p role="alert">{previewError}</p> : null}
      {preview ? (
        <>
          <DocumentPreview preview={preview} />
          {preview.document.status === 'PREVIEW_READY' ? (
            <section className="approval-bar" aria-label="Preview decision">
              <div>
                <strong>Preview complete</strong>
                <span>Approve this version or reject it from ingestion.</span>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="primary-button"
                  disabled={decisionPending}
                  onClick={() => void decide('approve')}
                >
                  {decisionPending ? 'Saving…' : 'Approve'}
                </button>
                <button
                  type="button"
                  disabled={decisionPending}
                  onClick={() => void decide('reject')}
                >
                  Reject
                </button>
              </div>
            </section>
          ) : null}
        </>
      ) : null}

      <DeleteDocumentDialog
        document={deleteTarget}
        deleting={deleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={(document) => void confirmDelete(document)}
      />
    </section>
  )
}
