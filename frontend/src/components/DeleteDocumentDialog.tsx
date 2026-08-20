import type { DocumentSummary } from '../types/documents'

interface DeleteDocumentDialogProps {
  document: DocumentSummary | null
  deleting: boolean
  onCancel: () => void
  onConfirm: (document: DocumentSummary) => void
}

export function DeleteDocumentDialog({
  document,
  deleting,
  onCancel,
  onConfirm,
}: DeleteDocumentDialogProps) {
  if (!document) {
    return null
  }

  return (
    <div className="dialog-backdrop">
      <section
        className="confirmation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <p className="eyebrow">Destructive action</p>
        <h2 id="delete-dialog-title">Delete this document?</h2>
        <p id="delete-dialog-description">
          <strong>{document.filename}</strong>, currently at version{' '}
          <strong>{document.version_number}</strong>, and all of its versions
          will be unavailable immediately. This action cannot be undone from
          this screen.
        </p>
        <div className="button-row">
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            autoFocus
          >
            Cancel
          </button>
          <button
            type="button"
            className="danger-button"
            onClick={() => onConfirm(document)}
            disabled={deleting}
          >
            {deleting ? 'Deleting…' : 'Delete document'}
          </button>
        </div>
      </section>
    </div>
  )
}
