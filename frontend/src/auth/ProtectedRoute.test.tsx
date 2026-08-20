import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { App } from '../App'
import { AuthProvider } from './AuthProvider'

describe('ProtectedRoute', () => {
  it('clears an invalid stored session and returns to login', async () => {
    sessionStorage.setItem('secure-portfolio-access-token', 'expired-token')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'invalid_session',
              message: 'Session is invalid or expired.',
            },
            request_id: 'expired-session',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(
      await screen.findByRole('heading', {
        name: 'Sign in to your authorized workspace',
      }),
    ).toBeInTheDocument()
    expect(sessionStorage.getItem('secure-portfolio-access-token')).toBeNull()
  })
})
