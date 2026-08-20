import type { IngestionStatus } from '../types/documents'

function statusLabel(status: IngestionStatus) {
  return status.toLowerCase().replaceAll('_', ' ')
}

export function IngestionStatusBadge({ status }: { status: IngestionStatus }) {
  return (
    <span
      className={`status-badge status-badge--${status.toLowerCase()}`}
      data-status={status}
    >
      {statusLabel(status)}
    </span>
  )
}
