import { describe, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import { searchAuthorizedDocuments } from './search'
import { authorizedSearchData } from '../test/searchFixtures'

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('searchAuthorizedDocuments', () => {
  it('posts only the bounded query and top_k with the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        data: authorizedSearchData,
        request_id: 'search-request',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      searchAuthorizedDocuments('signed-alice-token', {
        query: '  operating margin  ',
        top_k: 5,
      }),
    ).resolves.toEqual({
      data: authorizedSearchData,
      request_id: 'search-request',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/development/authorized-search')
    expect(options.method).toBe('POST')
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer signed-alice-token',
      'Content-Type': 'application/json',
    })
    if (typeof options.body !== 'string') {
      throw new Error('Search body was not serialized')
    }
    expect(JSON.parse(options.body)).toEqual({
      query: 'operating margin',
      top_k: 5,
    })
  })

  it.each([
    [{ query: '   ', top_k: 5 }, 'invalid_search_query'],
    [{ query: 'x'.repeat(501), top_k: 5 }, 'invalid_search_query'],
    [{ query: 'margin', top_k: 0 }, 'invalid_top_k'],
    [{ query: 'margin', top_k: 21 }, 'invalid_top_k'],
    [{ query: 'margin', top_k: 1.5 }, 'invalid_top_k'],
  ])('rejects invalid input before making a request', async (input, code) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      searchAuthorizedDocuments('signed-token', input),
    ).rejects.toMatchObject({ code })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects malformed success data instead of rendering it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: {
            ...authorizedSearchData,
            results: [
              {
                ...authorizedSearchData.results[0],
                excerpt: { unsafe: 'not text' },
              },
            ],
          },
          request_id: 'malformed-search-request',
        }),
      ),
    )

    await expect(
      searchAuthorizedDocuments('signed-token', {
        query: 'margin',
        top_k: 5,
      }),
    ).rejects.toEqual(
      new ApiError(
        'Backend returned an invalid response.',
        200,
        'invalid_response',
        'malformed-search-request',
      ),
    )
  })

  it('preserves a safe error envelope and request ID', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'forbidden',
              message: 'Document query access is not available.',
            },
            request_id: 'denied-search-request',
          }),
          { status: 403, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(
      searchAuthorizedDocuments('signed-token', {
        query: 'margin',
        top_k: 5,
      }),
    ).rejects.toEqual(
      new ApiError(
        'Document query access is not available.',
        403,
        'forbidden',
        'denied-search-request',
      ),
    )
  })
})
