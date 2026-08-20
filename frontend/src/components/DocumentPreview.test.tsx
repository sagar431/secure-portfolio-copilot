import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DocumentPreview } from './DocumentPreview'
import { pdfPreview, spreadsheetPreview } from '../test/documentFixtures'

describe('DocumentPreview', () => {
  it('renders PDF page provenance and document metadata', () => {
    render(<DocumentPreview preview={pdfPreview} />)

    expect(screen.getByRole('heading', { name: 'Page 1' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Page 2' })).toBeInTheDocument()
    expect(screen.getByText(pdfPreview.document.checksum)).toBeInTheDocument()
    expect(screen.getByText('finance only')).toBeInTheDocument()
  })

  it('renders sheet, row, and cell provenance while keeping formula text inert', () => {
    const { container } = render(
      <DocumentPreview preview={spreadsheetPreview} />,
    )

    expect(
      screen.getByRole('heading', { name: 'Sheet: P&L' }),
    ).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getAllByText('2')).toHaveLength(2)
    expect(within(table).getByText('B2')).toBeInTheDocument()
    expect(within(table).getByText('=SUM(B3:B4)')).toBeInTheDocument()
    expect(container.querySelector('script')).toBeNull()
    expect(
      screen.getByText('Formula-like cells are displayed as inert text.'),
    ).toBeInTheDocument()
  })
})
