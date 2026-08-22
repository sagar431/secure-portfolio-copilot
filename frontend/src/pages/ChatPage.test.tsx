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
  resolveAgentApproval: vi.fn(),
  stopAgentRun: vi.fn(),
  changeAgentRequest: vi.fn(),
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

function pendingApprovalData() {
  return {
    outcome: 'awaiting_approval' as const,
    conversation_id: conversationData.id,
    user_message_id: '81818181-8181-4181-8181-818181818181',
    agent_session_id: '82828282-8282-4282-8282-828282828282',
    agent_control_mode: 'guided' as const,
    approval: {
      approval_id: '83838383-8383-4383-8383-838383838383',
      run_id: '82828282-8282-4282-8282-828282828282',
      status: 'PENDING' as const,
      action_label: 'Search authorized documents <script>alert(1)</script>',
      safe_explanation:
        'Use an allow-listed tool within your current authorized scope.',
      tool_name: 'portfolio.search_authorized_documents' as const,
      risk_level: 'LOW_READ_ONLY' as const,
      resource_type: 'authorized portfolio documents' as const,
      estimated_cost_class: 'low' as const,
      safe_scope_summary: 'Orion Capital · Finance',
      remaining_budget: { steps: 4, tools: 4 },
      expires_at: '2099-08-22T12:00:00Z',
    },
  }
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
        'auto',
      ),
    )
    expect(screen.getByText(groundedAnswerData.answer)).toBeInTheDocument()
    const routeDetails = screen.getByLabelText('Response route details')
    expect(within(routeDetails).getByText('Auto')).toBeInTheDocument()
    expect(within(routeDetails).getByText('Fast')).toBeInTheDocument()
    expect(
      within(routeDetails).getByText('Gemini 3.1 Flash Lite'),
    ).toBeInTheDocument()
    expect(
      within(routeDetails).getByText('Simple high-confidence evidence'),
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
        'auto',
        'balanced',
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

  it('renders a safe accessible approval card and disables duplicate resolution clicks', async () => {
    const pending = pendingApprovalData()
    vi.mocked(chatApi.runConversationAgent).mockResolvedValueOnce({
      data: pending,
      request_id: 'pending-request',
    })
    let finish!: (value: {
      data: typeof agentRunData
      request_id: string
    }) => void
    vi.mocked(chatApi.resolveAgentApproval).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.click(screen.getByRole('radio', { name: /Guided/ }))
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Use the approved document tools.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))

    const card = await screen.findByRole('region', {
      name: /Search authorized documents/,
    })
    expect(
      within(card).getByText('Orion Capital · Finance'),
    ).toBeInTheDocument()
    expect(within(card).getByText('4 steps · 4 tools')).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect(within(card).queryByText(/raw arguments/i)).toBeInTheDocument()

    const approve = within(card).getByRole('button', { name: 'Approve once' })
    fireEvent.click(approve)
    await waitFor(() => expect(approve).toBeDisabled())
    fireEvent.click(approve)
    expect(chatApi.resolveAgentApproval).toHaveBeenCalledTimes(1)
    finish({ data: agentRunData, request_id: 'approved-request' })
    expect(await screen.findByText(/Run completed after/)).toBeInTheDocument()
  })

  it('keeps response and agent-control modes independent', async () => {
    vi.mocked(chatApi.runConversationAgent).mockResolvedValueOnce({
      data: pendingApprovalData(),
      request_id: 'pending-request',
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    const responseModes = screen.getByRole('group', { name: 'Response mode' })
    const controlModes = screen.getByRole('group', {
      name: 'Agent control mode',
    })
    expect(within(responseModes).getAllByRole('radio')).toHaveLength(3)
    expect(within(controlModes).getAllByRole('radio')).toHaveLength(3)
    fireEvent.click(within(responseModes).getByRole('radio', { name: /Deep/ }))
    fireEvent.click(within(controlModes).getByRole('radio', { name: /Guided/ }))
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Use one authorized tool.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))
    await waitFor(() =>
      expect(chatApi.runConversationAgent).toHaveBeenCalledWith(
        'signed-alice-token',
        conversationData.id,
        'Use one authorized tool.',
        expect.any(AbortSignal),
        'deep',
        'guided',
      ),
    )
  })

  it('supports reject, stop, and changed-request resolution paths', async () => {
    const pending = pendingApprovalData()
    vi.mocked(chatApi.runConversationAgent).mockResolvedValue({
      data: pending,
      request_id: 'pending-request',
    })
    vi.mocked(chatApi.resolveAgentApproval).mockResolvedValueOnce({
      data: {
        outcome: 'terminated',
        run_id: pending.agent_session_id,
        status: 'REJECTED',
        safe_message: 'The action was rejected and not run.',
      },
      request_id: 'reject-request',
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.click(screen.getByRole('radio', { name: /Guided/ }))
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Reject this action.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    expect(
      await screen.findByText('The action was rejected and not run.'),
    ).toBeInTheDocument()
    expect(chatApi.resolveAgentApproval).toHaveBeenCalledWith(
      'signed-alice-token',
      pending.agent_session_id,
      pending.approval.approval_id,
      'reject',
    )

    vi.mocked(chatApi.stopAgentRun).mockResolvedValueOnce({
      data: {
        outcome: 'terminated',
        run_id: pending.agent_session_id,
        status: 'CANCELLED',
        safe_message: 'The run was stopped safely.',
      },
      request_id: 'stop-request',
    })
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Stop this action.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Stop run' }))
    expect(
      await screen.findByText('The run was stopped safely.'),
    ).toBeInTheDocument()

    const changed = {
      ...pending,
      agent_session_id: '84848484-8484-4484-8484-848484848484',
      approval: {
        ...pending.approval,
        approval_id: '85858585-8585-4585-8585-858585858585',
        run_id: '84848484-8484-4484-8484-848484848484',
      },
    }
    vi.mocked(chatApi.changeAgentRequest).mockResolvedValueOnce({
      data: changed,
      request_id: 'change-request',
    })
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Change this action.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))
    fireEvent.click(
      await screen.findByRole('button', { name: 'Change request' }),
    )
    fireEvent.change(screen.getByLabelText('Changed request'), {
      target: { value: 'Use a narrower approved request.' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Submit changed request' }),
    )
    expect(
      await screen.findByText(/old run was cancelled and a new bounded plan/i),
    ).toBeInTheDocument()
    expect(chatApi.changeAgentRequest).toHaveBeenCalledWith(
      'signed-alice-token',
      pending.agent_session_id,
      pending.approval.approval_id,
      'Use a narrower approved request.',
    )
  })

  it('removes replayed approvals after a fail-closed response', async () => {
    const pending = pendingApprovalData()
    vi.mocked(chatApi.runConversationAgent).mockResolvedValueOnce({
      data: pending,
      request_id: 'pending-request',
    })
    vi.mocked(chatApi.resolveAgentApproval).mockRejectedValueOnce(
      new ApiError(
        'unsafe detail',
        409,
        'approval_unavailable',
        'replay-request',
      ),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.click(screen.getByRole('radio', { name: /Guided/ }))
    fireEvent.change(screen.getByLabelText('Ask about approved documents'), {
      target: { value: 'Replay this action.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run bounded agent' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Approve once' }))
    expect(
      await screen.findByText(
        /could not be resumed safely and was not executed/i,
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Approve once' }),
    ).not.toBeInTheDocument()
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
      'auto',
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
    expect(
      screen.getByRole('radio', { name: /^Auto Recommended/ }),
    ).toBeDisabled()
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

  it('defaults to Auto and sends the user-selected response mode', async () => {
    vi.mocked(chatApi.sendConversationMessage).mockResolvedValueOnce({
      data: {
        ...groundedAnswerData,
        requested_response_mode: 'deep',
        resolved_response_mode: 'deep',
        model_name: 'Gemini 3.7 Flash',
        route_reason: 'USER_REQUESTED_DEEP',
      },
      request_id: 'deep-answer-request',
    })
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    const responseModeGroup = screen.getByRole('group', {
      name: 'Response mode',
    })
    const modeRadios = within(responseModeGroup).getAllByRole('radio')
    expect(modeRadios).toHaveLength(3)
    expect(
      modeRadios.every(
        (radio) => radio.getAttribute('name') === 'response-mode',
      ),
    ).toBe(true)
    expect(
      within(responseModeGroup).getByRole('radio', { name: /Auto/ }),
    ).toBeChecked()

    fireEvent.click(
      within(responseModeGroup).getByRole('radio', { name: /Deep/ }),
    )
    submitQuestion()

    await waitFor(() =>
      expect(chatApi.sendConversationMessage).toHaveBeenCalledWith(
        'signed-alice-token',
        conversationData.id,
        'Why did margin improve?',
        expect.any(AbortSignal),
        'deep',
      ),
    )
    const routeDetails = await screen.findByLabelText('Response route details')
    expect(within(routeDetails).getAllByText('Deep')).toHaveLength(2)
    expect(
      within(routeDetails).getByText('Gemini 3.7 Flash'),
    ).toBeInTheDocument()
    expect(
      within(routeDetails).getByText('User explicitly requested Deep'),
    ).toBeInTheDocument()
  })

  it('renders a safe Fast upgrade card and resubmits only after Continue with Deep', async () => {
    vi.mocked(chatApi.sendConversationMessage).mockRejectedValueOnce(
      new ApiError(
        'provider details must not be rendered',
        409,
        'deep_mode_required',
        'upgrade-request',
      ),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.click(screen.getByRole('radio', { name: /Fast/ }))
    submitQuestion('  Compare Orion revenue across documents.  ')

    expect(
      await screen.findByRole('heading', {
        name: 'This request needs Deep mode because it requires broader analysis.',
      }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/provider details/)).not.toBeInTheDocument()
    expect(chatApi.sendConversationMessage).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Deep' }))

    await waitFor(() =>
      expect(chatApi.sendConversationMessage).toHaveBeenLastCalledWith(
        'signed-alice-token',
        conversationData.id,
        'Compare Orion revenue across documents.',
        expect.any(AbortSignal),
        'deep',
      ),
    )
    expect(chatApi.sendConversationMessage).toHaveBeenCalledTimes(2)
  })

  it('cancels a Fast upgrade without making another request', async () => {
    vi.mocked(chatApi.sendConversationMessage).mockRejectedValueOnce(
      new ApiError('safe', 409, 'deep_mode_required', 'upgrade-request'),
    )
    renderPage()
    await screen.findByRole('heading', { name: 'Orion finance review' })
    fireEvent.click(screen.getByRole('radio', { name: /Fast/ }))
    submitQuestion('Compare Orion revenue.')
    await screen.findByRole('button', { name: 'Continue with Deep' })

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(
      screen.queryByRole('button', { name: 'Continue with Deep' }),
    ).not.toBeInTheDocument()
    expect(chatApi.sendConversationMessage).toHaveBeenCalledTimes(1)
  })
})
