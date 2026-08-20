import { describe, expect, it, vi } from 'vitest'

import {
  createConversation,
  listConversations,
  runConversationAgent,
  sendConversationMessage,
} from './chat'
import { ApiError } from './client'
import {
  agentRunData,
  conversationData,
  groundedAnswerData,
  insufficientAnswerData,
} from '../test/chatFixtures'

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('conversation API', () => {
  it('lists only strict owned conversation summaries with a bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        data: { conversations: [conversationData] },
        request_id: 'conversation-list-request',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(listConversations('signed-token')).resolves.toEqual({
      data: { conversations: [conversationData] },
      request_id: 'conversation-list-request',
    })
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/conversations')
    expect(options.method).toBe('GET')
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer signed-token',
    })
  })

  it('creates a conversation using only a trimmed nullable title', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        data: { conversation: conversationData },
        request_id: 'conversation-create-request',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await createConversation('signed-token', '  Orion finance review  ')
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(options.method).toBe('POST')
    if (typeof options.body !== 'string') {
      throw new Error('Conversation body was not serialized')
    }
    expect(JSON.parse(options.body)).toEqual({
      title: 'Orion finance review',
    })
  })

  it('posts only normalized content and accepts a validated grounded answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        data: groundedAnswerData,
        request_id: 'grounded-answer-request',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      sendConversationMessage(
        'signed-token',
        conversationData.id,
        '  Why did margin improve?  ',
      ),
    ).resolves.toEqual({
      data: groundedAnswerData,
      request_id: 'grounded-answer-request',
    })
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain(`/api/conversations/${conversationData.id}/messages`)
    if (typeof options.body !== 'string') {
      throw new Error('Message body was not serialized')
    }
    expect(JSON.parse(options.body)).toEqual({
      content: 'Why did margin improve?',
    })
  })

  it('accepts the controlled insufficient-evidence response without claims or citations', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: insufficientAnswerData,
          request_id: 'insufficient-request',
        }),
      ),
    )

    await expect(
      sendConversationMessage(
        'signed-token',
        conversationData.id,
        'Unsupported question',
      ),
    ).resolves.toMatchObject({ data: { status: 'insufficient_evidence' } })
  })

  it('posts only normalized content and accepts a strict sanitized agent run', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        data: agentRunData,
        request_id: 'agent-run-request',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      runConversationAgent(
        'signed-token',
        conversationData.id,
        '  Use the bounded workflow.  ',
      ),
    ).resolves.toEqual({
      data: agentRunData,
      request_id: 'agent-run-request',
    })
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain(
      `/api/conversations/${conversationData.id}/agent-runs`,
    )
    expect(options.method).toBe('POST')
    if (typeof options.body !== 'string') {
      throw new Error('Agent run body was not serialized')
    }
    expect(JSON.parse(options.body)).toEqual({
      content: 'Use the bounded workflow.',
    })
  })

  it.each([
    [
      'raw prompt data',
      {
        ...agentRunData,
        trace: [
          {
            ...agentRunData.trace[0],
            raw_prompt: 'private prompt',
          },
          ...agentRunData.trace.slice(1),
        ],
      },
    ],
    [
      'tool arguments',
      {
        ...agentRunData,
        trace: [
          {
            ...agentRunData.trace[0],
            tool_arguments: { tenant_id: 'forged-tenant' },
          },
          ...agentRunData.trace.slice(1),
        ],
      },
    ],
    [
      'authorization scope',
      {
        ...agentRunData,
        authorization_scope: { tenant_id: 'restricted-tenant' },
      },
    ],
    [
      'raw reasoning',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === 1
            ? { ...event, reasoning: 'hidden chain of thought' }
            : event,
        ),
      },
    ],
    [
      'a model-encoded unapproved action name',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === 1
            ? { ...event, action_name: 'portfolio.private_query_fragment' }
            : event,
        ),
      },
    ],
    [
      'a model-encoded trace reason code',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === 1
            ? { ...event, reason_code: 'PRIVATE_QUERY_FRAGMENT' }
            : event,
        ),
      },
    ],
    [
      'a non-host trace event ID',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === 0 ? { ...event, event_id: 'model-controlled-id' } : event,
        ),
      },
    ],
    [
      'a non-host evidence reference',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === 1
            ? { ...event, evidence_reference_ids: ['private-fragment'] }
            : event,
        ),
      },
    ],
    [
      'a non-host stopping reason',
      {
        ...agentRunData,
        stopping_reason: 'private_query_fragment',
      },
    ],
    [
      'a trace without an explicit terminal event',
      { ...agentRunData, trace: agentRunData.trace.slice(0, -1) },
    ],
    [
      'partial evidence on a non-completed run',
      {
        ...agentRunData,
        terminal_status: 'limit_reached',
        trace: agentRunData.trace.map((event, index) =>
          index === agentRunData.trace.length - 1
            ? { ...event, status: 'terminated' }
            : event,
        ),
      },
    ],
    [
      'a mismatched completed terminal event',
      {
        ...agentRunData,
        trace: agentRunData.trace.map((event, index) =>
          index === agentRunData.trace.length - 1
            ? { ...event, status: 'terminated' }
            : event,
        ),
      },
    ],
  ])('rejects agent output containing %s', async (_case, data) => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ data, request_id: 'invalid-agent-request' }),
        ),
    )

    await expect(
      runConversationAgent(
        'signed-token',
        conversationData.id,
        'Use the bounded workflow.',
      ),
    ).rejects.toEqual(
      new ApiError(
        'Backend returned an invalid response.',
        200,
        'invalid_response',
        'invalid-agent-request',
      ),
    )
  })

  it.each([
    ['blank content', ' ', 'invalid_chat_question'],
    ['oversized content', 'x'.repeat(1_001), 'invalid_chat_question'],
  ])('rejects %s before a request', async (_case, content, code) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      sendConversationMessage('signed-token', conversationData.id, content),
    ).rejects.toMatchObject({ code })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    [
      'an extra envelope key',
      {
        data: groundedAnswerData,
        request_id: 'strict-request',
        debug: 'must not pass',
      },
    ],
    [
      'an extra answer key',
      {
        data: { ...groundedAnswerData, raw_prompt: 'must not pass' },
        request_id: 'strict-request',
      },
    ],
    [
      'an unknown claim citation',
      {
        data: {
          ...groundedAnswerData,
          claims: [{ text: 'Unsupported.', citation_ids: ['C99'] }],
        },
        request_id: 'strict-request',
      },
    ],
    [
      'duplicate citation IDs',
      {
        data: {
          ...groundedAnswerData,
          citations: [
            groundedAnswerData.citations[0],
            groundedAnswerData.citations[0],
          ],
        },
        request_id: 'strict-request',
      },
    ],
    [
      'an unreferenced citation',
      {
        data: {
          ...groundedAnswerData,
          citations: [
            groundedAnswerData.citations[0],
            {
              ...groundedAnswerData.citations[0],
              citation_id: 'C2',
              chunk_id: '44444444-4444-4444-8444-444444444444',
            },
          ],
        },
        request_id: 'strict-request',
      },
    ],
    [
      'malformed provenance',
      {
        data: {
          ...groundedAnswerData,
          citations: [
            {
              ...groundedAnswerData.citations[0],
              sheet_name: null,
            },
          ],
        },
        request_id: 'strict-request',
      },
    ],
    [
      'evidence attached to an abstention',
      {
        data: {
          ...insufficientAnswerData,
          citations: groundedAnswerData.citations,
        },
        request_id: 'strict-request',
      },
    ],
    [
      'a mismatched conversation ID',
      {
        data: {
          ...groundedAnswerData,
          conversation_id: '33333333-3333-4333-8333-333333333333',
        },
        request_id: 'strict-request',
      },
    ],
  ])('rejects %s', async (_case, responseBody) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(responseBody)),
    )

    await expect(
      sendConversationMessage(
        'signed-token',
        conversationData.id,
        'Why did margin improve?',
      ),
    ).rejects.toEqual(
      new ApiError(
        'Backend returned an invalid response.',
        200,
        'invalid_response',
        'strict-request',
      ),
    )
  })

  it.each([
    [
      'unexpected conversation fields',
      { ...conversationData, tenant_id: 'must-not-pass' },
    ],
    ['an invalid timestamp', { ...conversationData, updated_at: 'yesterday' }],
  ])('rejects %s from the list', async (_case, conversation) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: { conversations: [conversation] },
          request_id: 'strict-list-request',
        }),
      ),
    )

    await expect(listConversations('signed-token')).rejects.toMatchObject({
      code: 'invalid_response',
      requestId: 'strict-list-request',
    })
  })
})
