import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { BackendHealth } from './BackendHealth'

describe('BackendHealth', () => {
  it('displays a safe backend error with its request ID', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'service_unavailable',
              message: 'Service is not ready.',
            },
            request_id: 'failure-test',
          }),
          { status: 503, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    render(<BackendHealth />)

    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
    expect(screen.getByText('Service is not ready.')).toBeInTheDocument()
    expect(screen.getByText('Request ID: failure-test')).toBeInTheDocument()
  })
})
