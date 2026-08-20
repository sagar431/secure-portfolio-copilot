import type { ApiErrorEnvelope, ApiSuccessEnvelope } from '../types/api'

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false
  }
  return (
    typeof value.error.code === 'string' &&
    typeof value.error.message === 'string' &&
    typeof value.request_id === 'string'
  )
}

export function isSuccessEnvelope<T>(
  value: unknown,
): value is ApiSuccessEnvelope<T> {
  return (
    isRecord(value) && 'data' in value && typeof value.request_id === 'string'
  )
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  token?: string
  signal?: AbortSignal
}

export async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiSuccessEnvelope<T>> {
  let response: Response
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`
  }
  try {
    response = await fetch(apiUrl(path), {
      method: options.method ?? 'GET',
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError('Unable to reach the backend.', 0, 'network_error', null)
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError(
      'Backend returned an invalid response.',
      response.status,
      'invalid_response',
      response.headers.get('X-Request-ID'),
    )
  }

  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(
        body.error.message,
        response.status,
        body.error.code,
        body.request_id,
      )
    }
    throw new ApiError(
      'Backend request failed.',
      response.status,
      'request_failed',
      response.headers.get('X-Request-ID'),
    )
  }

  if (!isSuccessEnvelope<T>(body)) {
    throw new ApiError(
      'Backend returned an invalid response.',
      response.status,
      'invalid_response',
      response.headers.get('X-Request-ID'),
    )
  }
  return body
}

export function getJson<T>(path: string, signal?: AbortSignal) {
  return requestJson<T>(path, { signal })
}
