import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'
import * as searchApi from './api/search'
import { AuthContext, type AuthContextValue } from './auth/context'
import type { Capability } from './types/auth'

vi.mock('./api/search', () => ({
  searchAuthorizedDocuments: vi.fn(),
}))

function authValue(name: string, capabilities: Capability[]): AuthContextValue {
  return {
    status: 'authenticated',
    currentUser: {
      identity: {
        id: `user-${name.toLowerCase()}`,
        email: `${name.toLowerCase()}@example.com`,
        display_name: name,
      },
      active_memberships: [],
      authorization_scope: {
        grants: [
          {
            workspace: {
              id: 'tenant-orion',
              slug: 'orion',
              name: 'Orion Capital',
            },
            company_ids: ['company-orion'],
            company_slugs: ['orion-main'],
            query_departments: capabilities.includes('QUERY_DOCUMENTS')
              ? ['finance', 'shared']
              : [],
            capabilities,
          },
        ],
      },
    },
    accessToken: `signed-${name.toLowerCase()}-token`,
    login: vi.fn(),
    logout: vi.fn(),
  }
}

function renderApp(value: AuthContextValue, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={value}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('authorized search routing', () => {
  it('shows development search navigation to QUERY_DOCUMENTS users', () => {
    renderApp(authValue('Alice', ['QUERY_DOCUMENTS']))

    expect(
      screen.getByRole('link', { name: 'Authorized search' }),
    ).toHaveAttribute('href', '/development/search')
  })

  it('gives Nora no nav or direct route access and makes no search request', () => {
    renderApp(authValue('Nora', ['MANAGE_UPLOADS']), '/development/search')

    expect(
      screen.getByRole('heading', {
        name: 'Your server-derived authorization scope',
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Authorized search' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Authorized document search' }),
    ).not.toBeInTheDocument()
    expect(searchApi.searchAuthorizedDocuments).not.toHaveBeenCalled()
  })
})
