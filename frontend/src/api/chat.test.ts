import { describe, expect, it, vi } from 'vitest'

import {
  createConversation,
  listConversations,
  sendConversationMessage,
} from './chat'
import { ApiError } from './client'
import {
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
