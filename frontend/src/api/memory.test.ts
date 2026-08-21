import { describe, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import { createPrivateMemory, inspectMemories } from './memory'

const memory = {
  id: 'memory-1',
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

function response(data: unknown) {
  return new Response(JSON.stringify({ data, request_id: 'memory-request' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('memory API', () => {
  it('creates only a source-free private memory without client ACL fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(memory))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createPrivateMemory('signed-token', {
        companyId: 'company-orion',
        content: 'Present values in INR crores.',
        expiresInDays: 90,
      }),
    ).resolves.toMatchObject({ data: memory })

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(options.headers).toMatchObject({
      Authorization: 'Bearer signed-token',
    })
    if (typeof options.body !== 'string') {
      throw new Error('Memory body was not serialized')
    }
    expect(JSON.parse(options.body)).toEqual({
      company_id: 'company-orion',
      content: 'Present values in INR crores.',
      expires_in_days: 90,
      scope: 'PRIVATE_USER',
      source_chunk_ids: [],
    })
  })

  it('fails closed on a malformed scoped-memory response', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          response({ memories: [{ ...memory, can_delete: 'yes' }] }),
        ),
    )

    await expect(inspectMemories('signed-token')).rejects.toEqual(
      new ApiError(
        'Backend returned an invalid response.',
        200,
        'invalid_response',
        'memory-request',
      ),
    )
  })

  it('rejects unexpected memory fields instead of rendering them', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          response({ memories: [{ ...memory, tenant_id: 'tenant-atlas' }] }),
        ),
    )

    await expect(inspectMemories('signed-token')).rejects.toMatchObject({
      code: 'invalid_response',
      requestId: 'memory-request',
    })
  })
})
