import { Link, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

export function ApplicationLayout() {
  const auth = useAuth()
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand" to="/">
          Secure Portfolio Copilot
        </Link>
        <div className="header-session">
          <span>{auth.currentUser?.identity.display_name}</span>
          <button type="button" className="logout-button" onClick={auth.logout}>
            Log out
          </button>
        </div>
      </header>
      <main className="page-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        Synthetic-data development environment · Identity and policy Step 2
      </footer>
    </div>
  )
}
