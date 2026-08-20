import { requestJson } from './client'
import type { MeData, TokenData } from '../types/auth'

export function login(email: string, password: string, signal?: AbortSignal) {
  return requestJson<TokenData>('/api/auth/login', {
    method: 'POST',
    body: { email, password },
    signal,
  })
}

export function getMe(token: string, signal?: AbortSignal) {
  return requestJson<MeData>('/api/auth/me', { token, signal })
}
