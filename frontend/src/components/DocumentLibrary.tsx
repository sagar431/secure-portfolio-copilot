import { IngestionStatusBadge } from './IngestionStatusBadge'
import type {
  DocumentFilters,
  DocumentSummary,
  IngestionOptionsData,
  IngestionStatus,
} from '../types/documents'

const statuses: IngestionStatus[] = [
  'UPLOADED',
  'VALIDATING',
  'PARSING',
  'PREVIEW_READY',
  'APPROVED',
  'REJECTED',
  'VALIDATION_FAILED',
  'PARSING_FAILED',
  'DELETED',
]

interface DocumentLibraryProps {
  documents: DocumentSummary[]
  total: number
  limit: number
  offset: number
  options: IngestionOptionsData
  filters: DocumentFilters
  loading: boolean
  selectedVersionId: string | null
  onFiltersChange: (filters: DocumentFilters) => void
  onSelect: (document: DocumentSummary) => void
  onNewVersion: (document: DocumentSummary) => void
  onDelete: (document: DocumentSummary) => void
}

function label(value: string) {
  return value.toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ')
}

function locationCount(document: DocumentSummary) {
  return document.source_type === 'PDF'
    ? document.page_count
    : document.sheet_count
}

export function DocumentLibrary({
  documents,
  total,
  limit,
  offset,
  options,
  filters,
  loading,
  selectedVersionId,
  onFiltersChange,
  onSelect,
  onNewVersion,
  onDelete,
}: DocumentLibraryProps) {
  const selectedTenant = options.tenants.find(
    (tenant) => tenant.id === filters.tenant_id,
  )
  const departmentOptions = Array.from(
    new Map(
      options.classification_pairs.map((pair) => [
        pair.department,
        { value: pair.department, label: label(pair.department) },
      ]),
    ).values(),
  )
  const documentTypeOptions = options.document_types

  return (
    <section
      className="ingestion-card library-card"
      aria-labelledby="library-title"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Manageable documents</p>
          <h2 id="library-title">Document library</h2>
          <span>{total} document(s)</span>
        </div>
        {loading ? <span role="status">Refreshing…</span> : null}
      </div>
      <div className="library-filters" aria-label="Document filters">
        <label>
          Tenant
          <select
            value={filters.tenant_id ?? ''}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                tenant_id: event.target.value || undefined,
                company_id: undefined,
                offset: 0,
              })
            }
          >
            <option value="">All manageable tenants</option>
            {options.tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Company
          <select
            value={filters.company_id ?? ''}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                company_id: event.target.value || undefined,
                offset: 0,
              })
            }
          >
            <option value="">All manageable companies</option>
            {(
              selectedTenant?.companies ??
              options.tenants.flatMap((tenant) => tenant.companies)
            ).map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Department
          <select
            value={filters.department ?? ''}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                department: event.target.value || undefined,
                offset: 0,
              })
            }
          >
            <option value="">All departments</option>
            {departmentOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Document type
          <select
            value={filters.document_type ?? ''}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                document_type: (event.target.value || undefined) as
                  DocumentFilters['document_type'] | undefined,
                offset: 0,
              })
            }
          >
            <option value="">All document types</option>
            {documentTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.status ?? ''}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                status: (event.target.value || undefined) as
                  IngestionStatus | undefined,
                offset: 0,
              })
            }
          >
            <option value="">All statuses</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {label(status)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {documents.length ? (
        <div className="table-scroll">
          <table className="document-table">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Scope</th>
                <th scope="col">Version</th>
                <th scope="col">Status</th>
                <th scope="col">Location count</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => {
                const canPreview = [
                  'PREVIEW_READY',
                  'APPROVED',
                  'REJECTED',
                ].includes(document.status)
                return (
                  <tr
                    key={document.version_id}
                    className={
                      selectedVersionId === document.version_id
                        ? 'selected-row'
                        : undefined
                    }
                  >
                    <th scope="row">
                      {document.filename}
                      {document.warnings.length ? (
                        <small>{document.warnings.length} warning(s)</small>
                      ) : null}
                    </th>
                    <td>
                      {document.tenant.name}
                      <small>
                        {document.company.name} · {label(document.department)}
                      </small>
                    </td>
                    <td>{document.version_number}</td>
                    <td>
                      <IngestionStatusBadge status={document.status} />
                    </td>
                    <td>{locationCount(document)}</td>
                    <td>
                      <div className="table-actions">
                        <button
                          type="button"
                          onClick={() => onSelect(document)}
                          disabled={!canPreview}
                          title={
                            canPreview
                              ? undefined
                              : 'Preview is available after parsing succeeds.'
                          }
                        >
                          Preview
                        </button>
                        <button
                          type="button"
                          onClick={() => onNewVersion(document)}
                          disabled={document.status === 'DELETED'}
                        >
                          New version
                        </button>
                        <button
                          type="button"
                          className="danger-text-button"
                          onClick={() => onDelete(document)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : loading ? null : (
        <p className="empty-state">
          No manageable documents match these filters.
        </p>
      )}
      {total > 0 ? (
        <nav className="library-pagination" aria-label="Document pages">
          <button
            type="button"
            disabled={loading || offset === 0}
            onClick={() =>
              onFiltersChange({
                ...filters,
                offset: Math.max(0, offset - limit),
              })
            }
          >
            Previous
          </button>
          <span>
            Showing {offset + 1}–{Math.min(offset + documents.length, total)} of{' '}
            {total}
          </span>
          <button
            type="button"
            disabled={loading || offset + documents.length >= total}
            onClick={() =>
              onFiltersChange({ ...filters, offset: offset + limit })
            }
          >
            Next
          </button>
        </nav>
      ) : null}
    </section>
  )
}
