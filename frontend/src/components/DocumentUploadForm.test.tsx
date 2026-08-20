import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DocumentUploadForm } from './DocumentUploadForm'
import { ingestionOptions } from '../test/documentFixtures'

const options = {
  ...ingestionOptions,
  tenants: [
    ...ingestionOptions.tenants,
    {
      id: 'tenant-pegasus',
      slug: 'pegasus',
      name: 'Pegasus Capital',
      companies: [
        {
          id: 'company-pegasus',
          slug: 'pegasus-main',
          name: 'Pegasus Portfolio Company',
        },
      ],
    },
  ],
}

function renderForm(onSubmit = vi.fn()) {
  render(
    <DocumentUploadForm
      options={options}
      phase="idle"
      progress={0}
      onSubmit={onSubmit}
      onCancelUpload={vi.fn()}
      onCancelVersion={vi.fn()}
    />,
  )
  return onSubmit
}

describe('DocumentUploadForm', () => {
  it('uses only backend-provided classification pairs', () => {
    renderForm()

    expect(screen.getByLabelText('Visibility')).toHaveValue(
      'DEPARTMENT_PRIVATE',
    )
    expect(screen.getByLabelText('Classification')).toHaveValue('FINANCE_ONLY')
    fireEvent.change(screen.getByLabelText('Department'), {
      target: { value: 'shared' },
    })
    expect(screen.getByLabelText('Visibility')).toHaveValue('TENANT_SHARED')
    expect(screen.getByLabelText('Classification')).toHaveValue('TENANT_SHARED')
    expect(
      screen.queryByRole('option', { name: 'Finance only' }),
    ).not.toBeInTheDocument()
  })

  it('resets the company when the trusted tenant changes', () => {
    renderForm()

    fireEvent.change(screen.getByLabelText('Tenant'), {
      target: { value: 'tenant-pegasus' },
    })
    expect(screen.getByLabelText('Portfolio company')).toHaveValue(
      'company-pegasus',
    )
  })

  it('requires a reporting period for backend-marked document types', () => {
    const onSubmit = renderForm()
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [new File(['%PDF'], 'report.pdf')] },
    })
    const form = screen.getByRole('button', { name: 'Upload' }).closest('form')
    if (!form) {
      throw new Error('Upload form was not rendered')
    }
    fireEvent.submit(form)

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter a reporting period for this document type.',
    )
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
