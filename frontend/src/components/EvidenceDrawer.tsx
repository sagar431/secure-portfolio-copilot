import { useEffect, useRef } from 'react'

import type { GroundedCitationData } from '../types/chat'

function range(start: number | string | null, end: number | string | null) {
  if (start === null) {
    return '—'
  }
  return end === null || end === start ? String(start) : `${start}–${end}`
}

export function EvidenceDrawer({
  citation,
  onClose,
}: {
  citation: GroundedCitationData | null
  onClose: () => void
}) {
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!citation) {
      return
    }
    const previouslyFocused = document.activeElement
    closeButton.current?.focus()
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('keydown', closeOnEscape)
      if (previouslyFocused instanceof HTMLElement) {
        previouslyFocused.focus()
      }
    }
  }, [citation, onClose])

  if (!citation) {
    return null
  }

  return (
    <aside
      className="evidence-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="evidence-drawer-title"
    >
      <div className="evidence-drawer__backdrop" onClick={onClose} />
      <div className="evidence-drawer__panel">
        <div className="evidence-drawer__heading">
          <div>
            <p className="eyebrow">Authorized evidence</p>
            <h2 id="evidence-drawer-title">{citation.document_title}</h2>
          </div>
          <button
            ref={closeButton}
            type="button"
            className="text-button"
            onClick={onClose}
          >
            Close evidence
          </button>
        </div>
        <p className="evidence-excerpt">{citation.excerpt}</p>
        <dl className="evidence-provenance">
          <div>
            <dt>Citation</dt>
            <dd>{citation.citation_id}</dd>
          </div>
          <div>
            <dt>Version</dt>
            <dd>{citation.version_number}</dd>
          </div>
          <div>
            <dt>Page</dt>
            <dd>{citation.page_number ?? '—'}</dd>
          </div>
          <div>
            <dt>Sheet</dt>
            <dd>{citation.sheet_name ?? '—'}</dd>
          </div>
          <div>
            <dt>Rows</dt>
            <dd>{range(citation.row_start, citation.row_end)}</dd>
          </div>
          <div>
            <dt>Cells</dt>
            <dd>{range(citation.cell_start, citation.cell_end)}</dd>
          </div>
          <div>
            <dt>Document ID</dt>
            <dd>{citation.document_id}</dd>
          </div>
          <div>
            <dt>Version ID</dt>
            <dd>{citation.document_version_id}</dd>
          </div>
          <div>
            <dt>Chunk ID</dt>
            <dd>{citation.chunk_id}</dd>
          </div>
        </dl>
        <p className="evidence-boundary-note">
          This excerpt and provenance were returned by the authorized grounded
          answer service. Document content is displayed as inert text.
        </p>
      </div>
    </aside>
  )
}
