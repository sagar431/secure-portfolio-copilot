import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'
import * as agentHistoryApi from './api/agentHistory'
import { AuthContext, type AuthContextValue } from './auth/context'
import type { Capability } from './types/auth'

vi.mock('./api/agentHistory', () => ({
  listAgentRuns: vi.fn(),
  getAgentRun: vi.fn(),
}))

function authValue(capabilities: Capability[]): AuthContextValue {
  return {
    status: 'authenticated',
    currentUser: {
      identity: { id: 'user', email: 'user@example.com', display_name: 'User' },
      active_memberships: [],
      authorization_scope: {
        grants: [
          {
            workspace: { id: 'tenant', slug: 'orion', name: 'Orion' },
            company_ids: [],
            company_slugs: [],
            query_departments: [],
            capabilities,
          },
        ],
      },
    },
    accessToken: 'signed-token',
    login: vi.fn(),
    logout: vi.fn(),
  }
}

function renderRoute(value: AuthContextValue) {
  return render(
    <MemoryRouter initialEntries={['/agent-history']}>
      <AuthContext.Provider value={value}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('agent history routing', () => {
  it('shows navigation and history only to QUERY_DOCUMENTS users', async () => {
    vi.mocked(agentHistoryApi.listAgentRuns).mockResolvedValueOnce({
      data: { runs: [], next_cursor: null },
      request_id: 'list',
    })
    renderRoute(authValue(['QUERY_DOCUMENTS']))
    expect(screen.getByRole('link', { name: 'Agent History' })).toHaveAttribute(
      'href',
      '/agent-history',
    )
    expect(
      screen.getByRole('heading', { name: 'Agent History' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: 'No agent runs yet' }),
    ).toBeInTheDocument()
  })

  it('redirects users without QUERY_DOCUMENTS and hides navigation', () => {
    renderRoute(authValue(['MANAGE_UPLOADS']))
    expect(
      screen.queryByRole('link', { name: 'Agent History' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Agent History' }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', {
        name: 'Your server-derived authorization scope',
      }),
    ).toBeInTheDocument()
    expect(agentHistoryApi.listAgentRuns).not.toHaveBeenCalled()
  })
})
