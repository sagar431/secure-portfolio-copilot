import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'

const demoUsers = [
  ['Nora', 'nora@example.com', 'Platform administrator'],
  ['Alice', 'alice@example.com', 'Orion Finance'],
  ['Leo', 'leo@example.com', 'Orion Legal'],
  ['Maya', 'maya@example.com', 'Orion Investment Committee'],
  ['Amir', 'amir@example.com', 'Atlas Finance'],
  ['Lina', 'lina@example.com', 'Atlas Legal'],
] as const

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (auth.status === 'authenticated') {
    return <Navigate to="/" replace />
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await auth.login(email, password)
      const from = (location.state as { from?: string } | null)?.from ?? '/'
      void navigate(from, { replace: true })
    } catch (caught: unknown) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Login failed. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <p className="eyebrow">Secure Portfolio Copilot</p>
        <h1 id="login-title">Sign in to your authorized workspace</h1>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            Email
            <input
              autoComplete="username"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error ? <p role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>

      {import.meta.env.DEV ? (
        <section className="demo-users" aria-labelledby="demo-users-title">
          <p className="development-badge">Development only</p>
          <h2 id="demo-users-title">Synthetic demo users</h2>
          <p>
            Select a card to fill the email. Use your local seeded demo
            password.
          </p>
          <div className="demo-user-grid">
            {demoUsers.map(([name, demoEmail, description]) => (
              <button
                className="demo-user-card"
                type="button"
                key={demoEmail}
                onClick={() => setEmail(demoEmail)}
              >
                <strong>{name}</strong>
                <span>{description}</span>
                <small>{demoEmail}</small>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  )
}
