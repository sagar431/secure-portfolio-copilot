import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { AuthProvider } from './auth/AuthProvider'

describe('App', () => {
  it('redirects an anonymous visitor to the login page', async () => {
    render(
      <MemoryRouter>
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
    expect(screen.getByText('Development only')).toBeInTheDocument()
  })

  it('logs out, clears the session, and returns to login', async () => {
    sessionStorage.setItem(
      'secure-portfolio-access-token',
      'signed-session-token',
    )
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              data: {
                identity: {
                  id: '770f9ed6-3f4f-41be-923b-310b8698d7aa',
                  email: 'alice@example.com',
                  display_name: 'Alice Finance Analyst',
                },
                active_memberships: [
                  {
                    id: '6eb114ad-d98c-46f4-92c9-ac3e17d9695c',
                    tenant: {
                      id: 'd63ba0c4-f759-4bbc-8672-0f857b3f801a',
                      slug: 'orion',
                      name: 'Orion Capital',
                    },
                    role: 'analyst',
                    primary_department: 'finance',
                  },
                ],
                authorization_scope: {
                  grants: [
                    {
                      workspace: {
                        id: 'd63ba0c4-f759-4bbc-8672-0f857b3f801a',
                        slug: 'orion',
                        name: 'Orion Capital',
                      },
                      company_ids: ['db22938f-f5ee-4376-bf9e-2a940d7b6928'],
                      company_slugs: ['orion-main'],
                      query_departments: ['finance', 'shared'],
                      capabilities: ['QUERY_DOCUMENTS'],
                    },
                  ],
                },
              },
              request_id: 'session-me',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              data: { status: 'healthy' },
              request_id: 'health-after-login',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
    )

    render(
      <MemoryRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Log out' }))

    expect(
      await screen.findByRole('heading', {
        name: 'Sign in to your authorized workspace',
      }),
    ).toBeInTheDocument()
    expect(sessionStorage.getItem('secure-portfolio-access-token')).toBeNull()
  })
})
