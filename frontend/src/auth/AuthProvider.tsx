import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { getMe, login as requestLogin } from '../api/auth'
import type { MeData } from '../types/auth'
import { AuthContext, type AuthStatus } from './context'

const TOKEN_KEY = 'secure-portfolio-access-token'

function storedToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [currentUser, setCurrentUser] = useState<MeData | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY)
    setAccessToken(null)
    setCurrentUser(null)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    const token = storedToken()
    if (!token) {
      setStatus('anonymous')
      return
    }
    const controller = new AbortController()
    void getMe(token, controller.signal)
      .then((response) => {
        setAccessToken(token)
        setCurrentUser(response.data)
        setStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        logout()
      })
    return () => controller.abort()
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    const tokenResponse = await requestLogin(email, password)
    const token = tokenResponse.data.access_token
    const meResponse = await getMe(token)
    sessionStorage.setItem(TOKEN_KEY, token)
    setAccessToken(token)
    setCurrentUser(meResponse.data)
    setStatus('authenticated')
  }, [])

  const value = useMemo(
    () => ({ status, currentUser, accessToken, login, logout }),
    [status, currentUser, accessToken, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
