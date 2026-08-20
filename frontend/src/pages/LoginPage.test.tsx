import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '../auth/AuthProvider'
import { LoginPage } from './LoginPage'

const aliceMe = {
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
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<h1>Authorized home</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  it('labels demo cards as development-only and fills only the email', async () => {
    renderLogin()

    fireEvent.click(await screen.findByRole('button', { name: /Alice/ }))

    expect(screen.getByLabelText('Email')).toHaveValue('alice@example.com')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByText('Development only')).toBeInTheDocument()
  })

  it('logs in, validates /me, and stores the bearer token for the session', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              access_token: 'signed-test-token',
              token_type: 'bearer',
              expires_in: 900,
            },
            request_id: 'login-success',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ data: aliceMe, request_id: 'me-success' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)
    renderLogin()

    fireEvent.change(await screen.findByLabelText('Email'), {
      target: { value: 'alice@example.com' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'local-demo-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(
      await screen.findByRole('heading', { name: 'Authorized home' }),
    ).toBeInTheDocument()
    expect(sessionStorage.getItem('secure-portfolio-access-token')).toBe(
      'signed-test-token',
    )
    const secondCall = fetchMock.mock.calls[1]
    const requestTarget = secondCall?.[0]
    const requestUrl =
      typeof requestTarget === 'string'
        ? requestTarget
        : requestTarget instanceof URL
          ? requestTarget.toString()
          : requestTarget?.url
    expect(requestUrl).toContain('/api/auth/me')
    expect(new Headers(secondCall?.[1]?.headers).get('Authorization')).toBe(
      'Bearer signed-test-token',
    )
  })

  it('shows the backend generic login error safely', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'invalid_credentials',
              message: 'Invalid email or password.',
            },
            request_id: 'login-denied',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    renderLogin()

    fireEvent.change(await screen.findByLabelText('Email'), {
      target: { value: 'unknown@example.com' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'wrong-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Invalid email or password.',
    )
  })
})
