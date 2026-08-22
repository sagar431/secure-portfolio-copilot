import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { AuthContext, type AuthContextValue } from './auth/context'
import type { Capability, MeData } from './types/auth'

const api = vi.hoisted(() => ({
  listEvaluations: vi.fn().mockResolvedValue({ data: { runs: [] } }),
  getEvaluation: vi.fn(),
  runEvaluation: vi.fn(),
  downloadEvaluationReport: vi.fn(),
}))

vi.mock('./api/evaluations', () => api)

function identity(capabilities: Capability[]): MeData {
  return {
    identity: { id: 'id', email: 'demo@example.com', display_name: 'Demo' },
    active_memberships: [],
    authorization_scope: {
      grants: [
        {
          workspace: { id: 'workspace', slug: 'platform', name: 'Platform' },
          company_ids: [],
          company_slugs: [],
          query_departments: [],
          capabilities,
        },
      ],
    },
  }
}

function renderApp(capabilities: Capability[]) {
  const value: AuthContextValue = {
    status: 'authenticated',
    currentUser: identity(capabilities),
    accessToken: 'token',
    login: vi.fn(),
    logout: vi.fn(),
  }
  return render(
    <MemoryRouter initialEntries={['/admin/evaluations']}>
      <AuthContext.Provider value={value}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('evaluation capability routing', () => {
  beforeEach(() => vi.clearAllMocks())
  it('shows navigation and dashboard only to platform administrators', async () => {
    renderApp(['ADMINISTER_PLATFORM'])
    expect(
      screen.getByRole('link', { name: 'Evaluations' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: 'Secure evaluation' }),
    ).toBeInTheDocument()
  })

  it.each<Capability>(['QUERY_DOCUMENTS', 'MANAGE_UPLOADS'])(
    'denies direct navigation for %s users without calling the API',
    (capability) => {
      renderApp([capability])
      expect(
        screen.queryByRole('link', { name: 'Evaluations' }),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByRole('heading', { name: 'Secure evaluation' }),
      ).not.toBeInTheDocument()
      expect(
        screen.getByRole('heading', {
          name: 'Your server-derived authorization scope',
        }),
      ).toBeInTheDocument()
      expect(api.listEvaluations).not.toHaveBeenCalled()
    },
  )
})
