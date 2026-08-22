import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import * as agentHistoryApi from '../api/agentHistory'
import { ApiError } from '../api/client'
import { AuthContext, type AuthContextValue } from '../auth/context'
import {
  agentHistoryDetail,
  agentHistorySummary,
} from '../test/agentHistoryFixtures'
import { AgentHistoryPage } from './AgentHistoryPage'

vi.mock('../api/agentHistory', () => ({
  listAgentRuns: vi.fn(),
  getAgentRun: vi.fn(),
}))

const auth: AuthContextValue = {
  status: 'authenticated',
  currentUser: {
    identity: {
      id: 'alice',
      email: 'alice@example.com',
      display_name: 'Alice',
    },
    active_memberships: [],
    authorization_scope: { grants: [] },
  },
  accessToken: 'signed-alice-token',
  login: vi.fn(),
  logout: vi.fn(),
}

function renderPage() {
  return render(
    <AuthContext.Provider value={auth}>
      <AgentHistoryPage />
    </AuthContext.Provider>,
  )
}

describe('AgentHistoryPage', () => {
  it('renders loading and empty states', async () => {
    let resolveList!: (
      value: Awaited<ReturnType<typeof agentHistoryApi.listAgentRuns>>,
    ) => void
    vi.mocked(agentHistoryApi.listAgentRuns).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveList = resolve
      }),
    )
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Loading agent history',
    )
    resolveList({ data: { runs: [], next_cursor: null }, request_id: 'empty' })
    expect(
      await screen.findByRole('heading', { name: 'No agent runs yet' }),
    ).toBeInTheDocument()
  })

  it('lists runs and expands an inert six-stage safe timeline', async () => {
    vi.mocked(agentHistoryApi.listAgentRuns).mockResolvedValueOnce({
      data: { runs: [agentHistorySummary], next_cursor: null },
      request_id: 'list',
    })
    vi.mocked(agentHistoryApi.getAgentRun).mockResolvedValueOnce({
      data: agentHistoryDetail,
      request_id: 'detail',
    })
    const { container } = renderPage()

    const button = await screen.findByRole('button', {
      name: 'View safe timeline',
    })
    fireEvent.click(button)

    const timeline = await screen.findByLabelText('Stored safe agent timeline')
    for (const stage of [
      'perception',
      'policy',
      'decision',
      'tool',
      'observation',
      'final',
    ]) {
      expect(within(timeline).getByText(stage)).toBeInTheDocument()
    }
    expect(screen.getByText(/<img src=x onerror=alert/)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
  })

  it('supports cursor pagination without replacing existing runs', async () => {
    vi.mocked(agentHistoryApi.listAgentRuns)
      .mockResolvedValueOnce({
        data: { runs: [agentHistorySummary], next_cursor: 'cursor-2' },
        request_id: 'page-1',
      })
      .mockResolvedValueOnce({
        data: {
          runs: [
            {
              ...agentHistorySummary,
              id: 'dce48f7c-499a-4637-9323-af0984c0a29f',
            },
          ],
          next_cursor: null,
        },
        request_id: 'page-2',
      })
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'Load more runs' }),
    )

    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2))
    expect(agentHistoryApi.listAgentRuns).toHaveBeenLastCalledWith(
      'signed-alice-token',
      'cursor-2',
    )
  })

  it('reloads a persisted awaiting-approval run from history', async () => {
    vi.mocked(agentHistoryApi.listAgentRuns).mockResolvedValueOnce({
      data: {
        runs: [
          {
            ...agentHistorySummary,
            agent_control_mode: 'guided',
            status: 'AWAITING_APPROVAL',
            safe_reason_code: 'USER_APPROVAL_REQUIRED',
            completed_at: null,
            step_count: 0,
          },
        ],
        next_cursor: null,
      },
      request_id: 'awaiting-list',
    })
    renderPage()
    expect(await screen.findByText('awaiting approval')).toBeInTheDocument()
    expect(screen.getByText('guided')).toBeInTheDocument()
    expect(screen.getByText('USER_APPROVAL_REQUIRED')).toBeInTheDocument()
  })

  it('renders safe list errors and generic inaccessible detail state', async () => {
    vi.mocked(agentHistoryApi.listAgentRuns)
      .mockRejectedValueOnce(
        new ApiError('internal details', 500, 'internal', 'request'),
      )
      .mockResolvedValueOnce({
        data: { runs: [agentHistorySummary], next_cursor: null },
        request_id: 'retry-list',
      })
    const first = renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Agent history could not be loaded safely.',
    )
    expect(screen.queryByText('internal details')).not.toBeInTheDocument()
    first.unmount()

    vi.mocked(agentHistoryApi.getAgentRun).mockRejectedValueOnce(
      new ApiError('foreign or missing', 404, 'not_found', 'detail'),
    )
    renderPage()
    fireEvent.click(
      await screen.findByRole('button', { name: 'View safe timeline' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This agent run is unavailable.',
    )
  })
})
