import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as chatApi from '../api/chat'
import { ApiError } from '../api/client'
import { AuthContext, type AuthContextValue } from '../auth/context'
import {
  agentRunData,
  calculationRunData,
  conversationData,
  groundedAnswerData,
  insufficientAnswerData,
} from '../test/chatFixtures'
import type { Capability } from '../types/auth'
import { ChatPage } from './ChatPage'

vi.mock('../api/chat', () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  runConversationAgent: vi.fn(),
  sendConversationMessage: vi.fn(),
}))

function authValue(capabilities: Capability[] = ['QUERY_DOCUMENTS']) {
  return {
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
            capabilities,
          },
        ],
      },
    },
    accessToken: 'signed-alice-token',
    login: vi.fn(),
    logout: vi.fn(),
  } satisfies AuthContextValue
}

function renderPage(value: AuthContextValue = authValue()) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <ChatPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

function submitQuestion(question = 'Why did margin improve?') {
  fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
    target: { value: question },
  })
  fireEvent.submit(
    screen.getByRole('button', { name: 'Ask copilot' }).closest('form')!,
  )
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(chatApi.listConversations).mockResolvedValue({
      data: { conversations: [conversationData] },
      request_id: 'conversation-list-request',
    })
    vi.mocked(chatApi.createConversation).mockResolvedValue({
      data: { conversation: conversationData },
      request_id: 'conversation-create-request',
    })
    vi.mocked(chatApi.sendConversationMessage).mockResolvedValue({
      data: groundedAnswerData,
      request_id: 'grounded-answer-request',
    })
    vi.mocked(chatApi.runConversationAgent).mockResolvedValue({
      data: agentRunData,
      request_id: 'agent-run-request',
    })
  })

  it('loads the owned conversation list and offers bounded suggestions', async () => {
    renderPage()

    expect(
      await screen.findByRole('button', { name: /Orion finance review/ }),
    ).toHaveAttribute('aria-current', 'page')
    expect(chatApi.listConversations).toHaveBeenCalledWith(
      'signed-alice-token',
      expect.any(AbortSignal),
    )
    fireEvent.click(
      screen.getByRole('button', {
        name: 'What changed in Orion’s operating margin?',
      }),
    )
    expect(screen.getByLabelText('Ask about approved documents')).toHaveValue(
      'What changed in Orion’s operating margin?',
    )
  })

  it('renders grounded claims as inert text and opens exact evidence provenance', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    submitQuestion('  Why did margin improve?  ')

    await waitFor(() =>
      expect(chatApi.sendConversationMessage).toHaveBeenCalledWith(
        'signed-alice-token',
        conversationData.id,
        'Why did margin improve?',
        expect.any(AbortSignal),
      ),
    )
    expect(screen.getByText(groundedAnswerData.answer)).toBeInTheDocument()
    expect(
      screen.getByText('Model route: Gemini 3.1 Flash Lite'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/google-vertex|openrouter/i),
    ).not.toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    fireEvent.click(
      screen.getByRole('button', {
        name: 'View evidence C1 from orion-finance.xlsx',
      }),
    )
    const drawer = screen.getByRole('dialog', { name: 'orion-finance.xlsx' })
    expect(within(drawer).getByText('Summary')).toBeInTheDocument()
    expect(within(drawer).getByText('4–8')).toBeInTheDocument()
    expect(within(drawer).getByText('A4–F8')).toBeInTheDocument()
    expect(
      within(drawer).getByText(groundedAnswerData.citations[0].excerpt),
    ).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    fireEvent.click(
      within(drawer).getByRole('button', { name: 'Close evidence' }),
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('runs the explicit bounded-agent path and renders only sanitized timeline fields', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: '  Use the approved document tools.  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))

    await waitFor(() =>
      expect(chatApi.runConversationAgent).toHaveBeenCalledWith(
        'signed-alice-token',
        conversationData.id,
        'Use the approved document tools.',
        expect.any(AbortSignal),
      ),
    )
    expect(chatApi.sendConversationMessage).not.toHaveBeenCalled()
    const timeline = screen.getByRole('region', {
      name: 'Bounded orchestration timeline',
    })
    expect(within(timeline).getByText('Session ID')).toBeInTheDocument()
    expect(within(timeline).getByText('Gemini 3.7 Flash')).toBeInTheDocument()
    expect(
      within(timeline).queryByText(/google-vertex|openrouter/i),
    ).not.toBeInTheDocument()
    expect(
      within(timeline).getByText(agentRunData.agent_session_id),
    ).toBeInTheDocument()
    expect(
      within(timeline).getByText('portfolio.search_authorized_documents'),
    ).toBeInTheDocument()
    expect(within(timeline).getByText('23 ms')).toBeInTheDocument()
    expect(within(timeline).getByText('COMPLETED')).toBeInTheDocument()
    expect(
      within(timeline).queryByText('private prompt'),
    ).not.toBeInTheDocument()
    expect(
      within(timeline).queryByText('hidden chain of thought'),
    ).not.toBeInTheDocument()
    expect(
      within(timeline).queryByText('restricted-tenant'),
    ).not.toBeInTheDocument()

    fireEvent.click(
      within(timeline).getAllByRole('button', { name: 'ev_1' })[0],
    )
    expect(
      screen.getByRole('dialog', { name: 'orion-finance.xlsx' }),
    ).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
  })

  it('renders deterministic formula, trusted inputs, result, and evidence controls', async () => {
    vi.mocked(chatApi.runConversationAgent).mockResolvedValueOnce({
      data: calculationRunData,
      request_id: 'calculation-run-request',
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Calculate Orion EBITDA margin for FY2025.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))

    const card = await screen.findByRole('article', {
      name: 'EBITDA margin calculation',
    })
    expect(within(card).getByText('10.00%')).toBeInTheDocument()
    expect(
      within(card).getByText(calculationRunData.calculations[0].formula),
    ).toBeInTheDocument()
    expect(within(card).getByText('1000 INR crore')).toBeInTheDocument()
    expect(
      within(card).getByText(/arithmetic was performed by host code/i),
    ).toBeInTheDocument()

    fireEvent.click(within(card).getByRole('button', { name: 'ev_1' }))
    const drawer = screen.getByRole('dialog', { name: 'orion-finance.xlsx' })
    expect(within(drawer).getByText('C2')).toBeInTheDocument()
  })

  it('creates a private conversation automatically before the first question', async () => {
    vi.mocked(chatApi.listConversations).mockResolvedValueOnce({
      data: { conversations: [] },
      request_id: 'empty-list-request',
    })
    renderPage()
    await screen.findByText(/first question will start a conversation/i)
    submitQuestion()

    await waitFor(() =>
      expect(chatApi.createConversation).toHaveBeenCalledWith(
        'signed-alice-token',
        null,
        expect.any(AbortSignal),
      ),
    )
    expect(chatApi.sendConversationMessage).toHaveBeenCalledWith(
      'signed-alice-token',
      conversationData.id,
      'Why did margin improve?',
      expect.any(AbortSignal),
    )
  })

  it('shows and cancels an in-flight generation without rendering a partial answer', async () => {
    vi.mocked(chatApi.sendConversationMessage).mockImplementation(
      (_token, _conversationId, _content, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            reject(
              new DOMException('Canceled with private details', 'AbortError'),
            )
          })
        }),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    submitQuestion()

    expect(
      screen.getByText(
        /Retrieving authorized evidence and validating citations/,
      ),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel response' }))

    expect(await screen.findByText('Request canceled')).toBeInTheDocument()
    expect(
      screen.queryByText(/Canceled with private details/),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(groundedAnswerData.answer),
    ).not.toBeInTheDocument()
  })

  it('renders a controlled insufficient-evidence state without citation controls', async () => {
    vi.mocked(chatApi.sendConversationMessage).mockResolvedValueOnce({
      data: insufficientAnswerData,
      request_id: 'insufficient-request',
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    submitQuestion('What is the moon made of?')

    expect(
      await screen.findByRole('heading', {
        name: 'I can’t support an answer from authorized documents',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText(insufficientAnswerData.answer)).toBeInTheDocument()
    expect(screen.queryByText('Claims and citations')).not.toBeInTheDocument()
  })

  it.each([
    [
      'provider timeout',
      new ApiError(
        'raw provider timeout and stack',
        503,
        'llm_timeout',
        'timeout-request',
      ),
      'Answer provider timed out',
      'timeout-request',
    ],
    [
      'authorization denial',
      new ApiError(
        'unknown forbidden resource detail',
        403,
        'forbidden',
        'denied-request',
      ),
      'Request not authorized',
      'denied-request',
    ],
    [
      'unexpected failure',
      new Error('provider key, stack, prompt, and document text'),
      'Safe answer unavailable',
      null,
    ],
  ])('shows a safe %s card', async (_case, failure, title, requestId) => {
    vi.mocked(chatApi.sendConversationMessage).mockRejectedValueOnce(failure)
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    submitQuestion()

    expect(
      await screen.findByRole('heading', { name: title }),
    ).toBeInTheDocument()
    if (requestId) {
      expect(screen.getByText(`Request ID: ${requestId}`)).toBeInTheDocument()
    }
    expect(
      screen.queryByText(/raw provider timeout and stack/),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/unknown forbidden resource detail/),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/provider key, stack/)).not.toBeInTheDocument()
  })

  it('rejects a blank question without calling the message API', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.submit(
      screen.getByRole('button', { name: 'Ask copilot' }).closest('form')!,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter a question before asking the copilot.',
    )
    expect(chatApi.sendConversationMessage).not.toHaveBeenCalled()
  })
})
