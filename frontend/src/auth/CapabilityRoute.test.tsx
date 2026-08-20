import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from './context'
import { CapabilityRoute } from './CapabilityRoute'
import type { Capability, MeData } from '../types/auth'

function userWith(capabilities: Capability[]): MeData {
  return {
    identity: {
      id: 'user-id',
      email: 'demo@example.com',
      display_name: 'Demo User',
    },
    active_memberships: [],
    authorization_scope: {
      grants: [
        {
          workspace: {
            id: 'workspace-id',
            slug: 'orion',
            name: 'Orion Capital',
          },
          company_ids: ['company-id'],
          company_slugs: ['orion-main'],
          query_departments: [],
          capabilities,
        },
      ],
    },
  }
}

function renderRoute(currentUser: MeData) {
  const value: AuthContextValue = {
    status: 'authenticated',
    currentUser,
    accessToken: 'signed-token',
    login: vi.fn(),
    logout: vi.fn(),
  }
  return render(
    <MemoryRouter initialEntries={['/admin/documents']}>
      <AuthContext.Provider value={value}>
        <Routes>
          <Route path="/" element={<h1>Authorized home</h1>} />
          <Route element={<CapabilityRoute capability="MANAGE_UPLOADS" />}>
            <Route
              path="/admin/documents"
              element={<h1>Document ingestion</h1>}
            />
          </Route>
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('CapabilityRoute', () => {
  it('renders upload management for a trusted MANAGE_UPLOADS grant', () => {
    renderRoute(userWith(['MANAGE_UPLOADS']))

    expect(
      screen.getByRole('heading', { name: 'Document ingestion' }),
    ).toBeInTheDocument()
  })

  it('redirects a non-admin without mounting the admin page', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    renderRoute(userWith(['QUERY_DOCUMENTS']))

    expect(
      screen.getByRole('heading', { name: 'Authorized home' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Document ingestion')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
