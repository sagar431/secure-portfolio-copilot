import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as memoryApi from '../api/memory'
import { AuthContext, type AuthContextValue } from '../auth/context'
import type { MemoryData } from '../types/memory'
import { MemoryPage } from './MemoryPage'

vi.mock('../api/memory', () => ({
  createPrivateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  inspectMemories: vi.fn(),
}))

const visibleMemory: MemoryData = {
  id: 'memory-private',
  company_id: 'company-orion',
  scope: 'PRIVATE_USER',
  owner_user_id: 'user-alice',
  department: 'finance',
  visibility: 'DEPARTMENT_PRIVATE',
  classification: 'FINANCE_ONLY',
  content: 'Present values in INR crores.',
  expires_at: '2026-11-19T00:00:00Z',
  created_at: '2026-08-21T00:00:00Z',
  can_delete: true,
  sources: [],
}

const auth: AuthContextValue = {
  status: 'authenticated',
  currentUser: {
    identity: {
      id: 'user-alice',
      email: 'alice@example.com',
      display_name: 'Alice Finance Analyst',
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
          query_departments: ['finance', 'shared'],
          capabilities: ['QUERY_DOCUMENTS'],
        },
      ],
    },
  },
  accessToken: 'signed-alice-token',
  login: vi.fn(),
  logout: vi.fn(),
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <MemoryPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

describe('MemoryPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(memoryApi.inspectMemories).mockResolvedValue({
      data: { memories: [visibleMemory] },
      request_id: 'memory-list',
    })
    vi.mocked(memoryApi.createPrivateMemory).mockResolvedValue({
      data: {
        ...visibleMemory,
        id: 'memory-new',
        content: 'Use concise tables.',
      },
      request_id: 'memory-create',
    })
    vi.mocked(memoryApi.deleteMemory).mockResolvedValue({
      data: { memory_id: visibleMemory.id, deleted: true },
      request_id: 'memory-delete',
    })
  })

  it('renders only the server-filtered list and creates a bounded private memory', async () => {
    renderPage()

    expect(await screen.findByText(visibleMemory.content)).toBeInTheDocument()
    expect(memoryApi.inspectMemories).toHaveBeenCalledWith(
      'signed-alice-token',
      expect.any(AbortSignal),
    )
    fireEvent.change(screen.getByLabelText('Preference'), {
      target: { value: 'Use concise tables.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save private memory' }))

    await waitFor(() =>
      expect(memoryApi.createPrivateMemory).toHaveBeenCalledWith(
        'signed-alice-token',
        {
          companyId: 'company-orion',
          content: 'Use concise tables.',
          expiresInDays: 90,
        },
      ),
    )
    expect(await screen.findByText('Use concise tables.')).toBeInTheDocument()
  })

  it('deletes a memory only when the server marks it deletable', async () => {
    renderPage()
    await screen.findByText(visibleMemory.content)

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() =>
      expect(memoryApi.deleteMemory).toHaveBeenCalledWith(
        'signed-alice-token',
        visibleMemory.id,
      ),
    )
    await waitFor(() =>
      expect(screen.queryByText(visibleMemory.content)).not.toBeInTheDocument(),
    )
  })
})
