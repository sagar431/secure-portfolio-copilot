import { BackendHealth } from '../components/BackendHealth'
import { AuthorizationScopePanel } from '../components/AuthorizationScopePanel'
import { useAuth } from '../auth/useAuth'

export function HomePage() {
  const auth = useAuth()
  return (
    <section className="hero" aria-labelledby="page-title">
      <p className="eyebrow">Identity and deterministic authorization</p>
      <h1 id="page-title">Your server-derived authorization scope</h1>
      <p className="hero-copy">
        The browser displays this scope but cannot change it. Protected requests
        reload active memberships and grants from the database.
      </p>
      {auth.currentUser ? (
        <AuthorizationScopePanel user={auth.currentUser} />
      ) : null}
      <BackendHealth />
    </section>
  )
}
