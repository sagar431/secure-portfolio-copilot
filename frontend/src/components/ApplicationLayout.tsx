import { Link, Outlet } from 'react-router-dom'

import { hasCapability } from '../auth/capabilities'
import { useAuth } from '../auth/useAuth'

export function ApplicationLayout() {
  const auth = useAuth()
  const canManageUploads = hasCapability(
    auth.currentUser?.authorization_scope.grants ?? [],
    'MANAGE_UPLOADS',
  )
  const canQueryDocuments = hasCapability(
    auth.currentUser?.authorization_scope.grants ?? [],
    'QUERY_DOCUMENTS',
  )
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand" to="/">
          Secure Portfolio Copilot
        </Link>
        <nav className="site-nav" aria-label="Primary navigation">
          <Link to="/">Scope</Link>
          {canManageUploads ? (
            <Link to="/admin/documents">Document ingestion</Link>
          ) : null}
          {canQueryDocuments ? <Link to="/chat">Grounded chat</Link> : null}
          {canQueryDocuments ? (
            <Link to="/memories">Memory inspector</Link>
          ) : null}
          {import.meta.env.DEV && canQueryDocuments ? (
            <Link to="/development/search">Authorized search</Link>
          ) : null}
        </nav>
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
        Synthetic-data development environment · Grounded portfolio chat
      </footer>
    </div>
  )
}
