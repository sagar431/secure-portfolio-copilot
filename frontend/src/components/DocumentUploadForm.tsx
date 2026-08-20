import { useRef, useState, type FormEvent } from 'react'

import type {
  DocumentSummary,
  IngestionOptionsData,
  UploadMetadata,
} from '../types/documents'

export type UploadPhase =
  'idle' | 'uploading' | 'processing' | 'complete' | 'error'

export interface UploadSubmission {
  metadata: UploadMetadata
  file: File
  documentId?: string
}

interface DocumentUploadFormProps {
  options: IngestionOptionsData
  targetDocument?: DocumentSummary | null
  phase: UploadPhase
  progress: number
  onSubmit: (submission: UploadSubmission) => void
  onCancelUpload: () => void
  onCancelVersion: () => void
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.ceil(bytes / 1024)} KB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function label(value: string) {
  return value.toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ')
}

export function DocumentUploadForm({
  options,
  targetDocument,
  phase,
  progress,
  onSubmit,
  onCancelUpload,
  onCancelVersion,
}: DocumentUploadFormProps) {
  const initialTenantId =
    targetDocument?.tenant.id ?? options.tenants[0]?.id ?? ''
  const [tenantId, setTenantId] = useState(initialTenantId)
  const initialTenant = options.tenants.find(
    (tenant) => tenant.id === initialTenantId,
  )
  const initialDepartment =
    targetDocument?.department ??
    options.classification_pairs[0]?.department ??
    ''
  const initialPair = options.classification_pairs.find(
    (pair) =>
      pair.department === initialDepartment &&
      (!targetDocument || pair.visibility === targetDocument.visibility),
  )
  const [companyId, setCompanyId] = useState(
    targetDocument?.company.id ?? initialTenant?.companies[0]?.id ?? '',
  )
  const [department, setDepartment] = useState(initialDepartment)
  const [visibility, setVisibility] = useState<UploadMetadata['visibility']>(
    targetDocument?.visibility ?? initialPair?.visibility ?? 'TENANT_SHARED',
  )
  const [classification, setClassification] = useState(
    targetDocument?.classification ??
      initialPair?.classification ??
      options.classification_pairs[0]?.classification ??
      'TENANT_SHARED',
  )
  const [documentType, setDocumentType] = useState<
    UploadMetadata['document_type']
  >(
    targetDocument?.document_type ??
      options.document_types[0]?.value ??
      'OTHER',
  )
  const [reportingPeriod, setReportingPeriod] = useState(
    targetDocument?.reporting_period ?? '',
  )
  const fileInput = useRef<HTMLInputElement>(null)
  const [localError, setLocalError] = useState<string | null>(null)

  const tenant =
    options.tenants.find((item) => item.id === tenantId) ?? options.tenants[0]
  const selectedType = options.document_types.find(
    (item) => item.value === documentType,
  )
  const allowedVisibilities = options.classification_pairs
    .filter((pair) => pair.department === department)
    .map((pair) => pair.visibility)
    .filter((value, index, values) => values.indexOf(value) === index)
  const allowedClassifications = options.classification_pairs.filter(
    (pair) => pair.department === department && pair.visibility === visibility,
  )
  const departments = options.classification_pairs
    .map((pair) => pair.department)
    .filter((value, index, values) => values.indexOf(value) === index)
  const isBusy = phase === 'uploading' || phase === 'processing'
  const lockedToExistingDocument = Boolean(targetDocument)

  function changeTenant(nextTenantId: string) {
    const nextTenant = options.tenants.find((item) => item.id === nextTenantId)
    setTenantId(nextTenantId)
    setCompanyId(nextTenant?.companies[0]?.id ?? '')
    setReportingPeriod('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)
    const file = fileInput.current?.files?.[0]
    if (!file) {
      setLocalError('Choose a PDF, XLSX, or CSV file.')
      return
    }
    if (selectedType?.reporting_period_required && !reportingPeriod.trim()) {
      setLocalError('Enter a reporting period for this document type.')
      return
    }
    if (file.size > options.limits.max_upload_bytes) {
      setLocalError(
        `The selected file exceeds the ${formatBytes(options.limits.max_upload_bytes)} upload limit.`,
      )
      return
    }
    onSubmit({
      metadata: {
        tenant_id: tenantId,
        company_id: companyId,
        department,
        visibility,
        classification,
        document_type: documentType,
        reporting_period: reportingPeriod.trim() || null,
      },
      file,
      documentId: targetDocument?.document_id,
    })
  }

  return (
    <section className="ingestion-card" aria-labelledby="upload-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Governed intake</p>
          <h2 id="upload-title">
            {targetDocument
              ? `Upload version ${targetDocument.version_number + 1}`
              : 'Upload a document'}
          </h2>
        </div>
        {targetDocument ? (
          <button
            type="button"
            className="text-button"
            onClick={onCancelVersion}
            disabled={isBusy}
          >
            Cancel new version
          </button>
        ) : null}
      </div>
      {targetDocument ? (
        <p className="supporting-copy">
          Creating a new version of <strong>{targetDocument.filename}</strong>.
          Its trusted classification remains locked.
        </p>
      ) : null}
      <form className="upload-form" onSubmit={submit}>
        <div className="form-grid">
          <label>
            Tenant
            <select
              value={tenantId}
              onChange={(event) => changeTenant(event.target.value)}
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {options.tenants.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Portfolio company
            <select
              value={companyId}
              onChange={(event) => setCompanyId(event.target.value)}
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {tenant?.companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Department
            <select
              value={department}
              onChange={(event) => {
                const nextDepartment = event.target.value
                const nextPair = options.classification_pairs.find(
                  (pair) => pair.department === nextDepartment,
                )
                setDepartment(nextDepartment)
                setVisibility(nextPair?.visibility ?? 'TENANT_SHARED')
                setClassification(nextPair?.classification ?? 'TENANT_SHARED')
              }}
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {departments.map((item) => (
                <option key={item} value={item}>
                  {label(item)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Visibility
            <select
              value={visibility}
              onChange={(event) => {
                const nextVisibility = event.target
                  .value as UploadMetadata['visibility']
                const nextPair = options.classification_pairs.find(
                  (pair) =>
                    pair.department === department &&
                    pair.visibility === nextVisibility,
                )
                setVisibility(nextVisibility)
                setClassification(nextPair?.classification ?? 'TENANT_SHARED')
              }}
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {allowedVisibilities.map((value) => {
                return (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                )
              })}
            </select>
          </label>
          <label>
            Classification
            <select
              value={classification}
              onChange={(event) =>
                setClassification(
                  event.target.value as UploadMetadata['classification'],
                )
              }
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {allowedClassifications.map((pair) => (
                <option key={pair.classification} value={pair.classification}>
                  {pair.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Document type
            <select
              value={documentType}
              onChange={(event) =>
                setDocumentType(
                  event.target.value as UploadMetadata['document_type'],
                )
              }
              required
              disabled={isBusy || lockedToExistingDocument}
            >
              {options.document_types.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reporting period
            <input
              value={reportingPeriod}
              onChange={(event) => setReportingPeriod(event.target.value)}
              required={selectedType?.reporting_period_required}
              disabled={isBusy || lockedToExistingDocument}
              placeholder="FY2025"
            />
          </label>
        </div>
        <label>
          File
          <input
            ref={fileInput}
            type="file"
            aria-label="File"
            accept={options.limits.extensions.join(',')}
            required
            disabled={isBusy}
          />
          <small>
            {options.limits.extensions.join(', ')} · Maximum{' '}
            {formatBytes(options.limits.max_upload_bytes)}
          </small>
        </label>
        {localError ? <p role="alert">{localError}</p> : null}
        {phase !== 'idle' ? (
          <div className="upload-progress" aria-live="polite">
            <div className="progress-track" aria-hidden="true">
              <span style={{ width: `${progress}%` }} />
            </div>
            <p role="status">
              {phase === 'uploading'
                ? `Uploading ${progress}%`
                : phase === 'processing'
                  ? 'Upload complete. Validating and parsing…'
                  : phase === 'complete'
                    ? 'Preview is ready.'
                    : 'Upload did not complete.'}
            </p>
          </div>
        ) : null}
        <div className="button-row">
          <button type="submit" className="primary-button" disabled={isBusy}>
            {isBusy
              ? 'Working…'
              : targetDocument
                ? 'Upload new version'
                : 'Upload'}
          </button>
          {isBusy ? (
            <button type="button" onClick={onCancelUpload}>
              Cancel upload
            </button>
          ) : null}
        </div>
      </form>
    </section>
  )
}
