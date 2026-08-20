import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'
import * as chatApi from './api/chat'
import { AuthContext, type AuthContextValue } from './auth/context'
import { conversationData } from './test/chatFixtures'
import type { Capability } from './types/auth'

vi.mock('./api/chat', () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  runConversationAgent: vi.fn(),
  sendConversationMessage: vi.fn(),
}))

function authValue(capabilities: Capability[]): AuthContextValue {
  return {
    status: 'authenticated',
    currentUser: {
      identity: {
        id: 'user-test',
        email: 'test@example.com',
        display_name: 'Test User',
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
            query_departments: ['finance'],
            capabilities,
          },
        ],
      },
    },
    accessToken: 'signed-test-token',
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

describe('grounded chat routing', () => {
  it('shows navigation and the secured workspace to QUERY_DOCUMENTS users', async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      data: { conversations: [conversationData] },
      request_id: 'list-request',
    })
    renderApp(authValue(['QUERY_DOCUMENTS']), '/chat')

    expect(screen.getByRole('link', { name: 'Grounded chat' })).toHaveAttribute(
      'href',
      '/chat',
    )
    expect(
      screen.getByRole('heading', { name: 'Grounded chat workspace' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: 'Orion finance review' }),
    ).toBeInTheDocument()
    expect(chatApi.listConversations).toHaveBeenCalledTimes(1)
  })

  it('gives users without QUERY_DOCUMENTS no navigation or direct route access', () => {
    renderApp(authValue(['MANAGE_UPLOADS']), '/chat')

    expect(
      screen.getByRole('heading', {
        name: 'Your server-derived authorization scope',
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Grounded chat' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Grounded chat workspace' }),
    ).not.toBeInTheDocument()
    expect(chatApi.listConversations).not.toHaveBeenCalled()
  })
})
