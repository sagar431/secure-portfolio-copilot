import { IngestionStatusBadge } from './IngestionStatusBadge'
import type { DocumentPreviewData } from '../types/documents'

const MAX_PAGES = 25
const MAX_SHEETS = 10
const MAX_ROWS_PER_SHEET = 100
const MAX_CELLS_PER_ROW = 50

function label(value: string) {
  return value.toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ')
}

function locationCount(preview: DocumentPreviewData) {
  return preview.content.kind === 'pdf'
    ? preview.document.page_count
    : preview.document.sheet_count
}

function Metadata({ preview }: { preview: DocumentPreviewData }) {
  const document = preview.document
  return (
    <dl className="document-metadata">
      <div>
        <dt>Filename</dt>
        <dd>{document.filename}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>
          <IngestionStatusBadge status={document.status} />
        </dd>
      </div>
      <div>
        <dt>Version</dt>
        <dd>{document.version_number}</dd>
      </div>
      <div>
        <dt>Detected type</dt>
        <dd>{document.source_type}</dd>
      </div>
      <div>
        <dt>Checksum</dt>
        <dd className="checksum">{document.checksum}</dd>
      </div>
      <div>
        <dt>Tenant / company</dt>
        <dd>
          {document.tenant.name} / {document.company.name}
        </dd>
      </div>
      <div>
        <dt>Department</dt>
        <dd>{label(document.department)}</dd>
      </div>
      <div>
        <dt>Visibility</dt>
        <dd>{label(document.visibility)}</dd>
      </div>
      <div>
        <dt>Classification</dt>
        <dd>{label(document.classification)}</dd>
      </div>
      <div>
        <dt>Document type</dt>
        <dd>{label(document.document_type)}</dd>
      </div>
      <div>
        <dt>Pages / sheets</dt>
        <dd>{locationCount(preview)}</dd>
      </div>
      <div>
        <dt>Rows / cells</dt>
        <dd>
          {document.row_count} / {document.cell_count}
        </dd>
      </div>
    </dl>
  )
}

function PdfPreview({ preview }: { preview: DocumentPreviewData }) {
  if (preview.content.kind !== 'pdf') {
    return null
  }
  const pages = preview.content.pages.slice(0, MAX_PAGES)
  return (
    <div className="pdf-preview">
      {pages.map((page) => (
        <article key={page.page_number} className="preview-page">
          <h3>Page {page.page_number}</h3>
          <pre>{page.text}</pre>
        </article>
      ))}
      {preview.content.pages.length > pages.length ? (
        <p className="preview-limit-note">
          Showing the first {pages.length} of {preview.content.page_count}{' '}
          pages.
        </p>
      ) : null}
    </div>
  )
}

function SpreadsheetPreview({ preview }: { preview: DocumentPreviewData }) {
  if (preview.content.kind !== 'spreadsheet') {
    return null
  }
  const sheets = preview.content.sheets.slice(0, MAX_SHEETS)
  return (
    <div className="spreadsheet-preview">
      {sheets.map((sheet) => {
        const rows = sheet.rows.slice(0, MAX_ROWS_PER_SHEET)
        return (
          <article key={sheet.sheet_name} className="preview-sheet">
            <div className="section-heading">
              <h3>Sheet: {sheet.sheet_name}</h3>
              <span>
                {sheet.row_count} rows · {sheet.column_count} columns
              </span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Row</th>
                    <th scope="col">Cell</th>
                    <th scope="col">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.flatMap((row) =>
                    row.cells.slice(0, MAX_CELLS_PER_ROW).map((cell) => (
                      <tr key={`${row.row_number}:${cell.coordinate}`}>
                        <th scope="row">{row.row_number}</th>
                        <td>{cell.coordinate}</td>
                        <td className="cell-value">
                          {cell.value === null ? '' : String(cell.value)}
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
            {sheet.rows.length > rows.length ? (
              <p className="preview-limit-note">
                Showing the first {rows.length} of {sheet.row_count} rows.
              </p>
            ) : null}
          </article>
        )
      })}
      {preview.content.sheets.length > sheets.length ? (
        <p className="preview-limit-note">
          Showing the first {sheets.length} of {preview.content.sheet_count}{' '}
          sheets.
        </p>
      ) : null}
    </div>
  )
}

export function DocumentPreview({ preview }: { preview: DocumentPreviewData }) {
  const warnings = Array.from(
    new Set([...preview.document.warnings, ...preview.warnings]),
  )
  return (
    <section
      className="ingestion-card preview-card"
      aria-labelledby="preview-title"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Parsed content</p>
          <h2 id="preview-title">Preview before approval</h2>
        </div>
      </div>
      <Metadata preview={preview} />
      {warnings.length ? (
        <aside className="warning-panel" aria-labelledby="warnings-title">
          <h3 id="warnings-title">Warnings</h3>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </aside>
      ) : null}
      <PdfPreview preview={preview} />
      <SpreadsheetPreview preview={preview} />
    </section>
  )
}
