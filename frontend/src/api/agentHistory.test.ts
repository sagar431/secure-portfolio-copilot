import { afterEach, describe, expect, it, vi } from 'vitest'

import { getAgentRun, listAgentRuns } from './agentHistory'
import {
  agentHistoryDetail,
  agentHistorySummary,
} from '../test/agentHistoryFixtures'

describe('agent history API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses bearer auth, an encoded cursor, and accepts exact safe list metadata', async () => {
    const fetchMock =
      vi.fn<
        (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
      >()
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { runs: [agentHistorySummary], next_cursor: null },
          request_id: 'list',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const response = await listAgentRuns('signed-token', 'next cursor')

    expect(response.data.runs).toEqual([agentHistorySummary])
    const [requestedUrl, options] = fetchMock.mock.calls[0]
    const url =
      typeof requestedUrl === 'string'
        ? requestedUrl
        : requestedUrl instanceof URL
          ? requestedUrl.href
          : requestedUrl.url
    expect(url).toContain('/api/agent-runs?limit=20&cursor=next+cursor')
    expect(new Headers(options?.headers).get('Authorization')).toBe(
      'Bearer signed-token',
    )
  })

  it('accepts exact safe detail metadata and rejects extra unsafe fields', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ data: agentHistoryDetail, request_id: 'detail' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
    )
    expect(
      (await getAgentRun('signed-token', agentHistoryDetail.id)).data,
    ).toEqual(agentHistoryDetail)

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { ...agentHistoryDetail, raw_prompt: 'unsafe' },
            request_id: 'unsafe-detail',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    await expect(
      getAgentRun('signed-token', agentHistoryDetail.id),
    ).rejects.toMatchObject({ code: 'invalid_response' })
  })
})
