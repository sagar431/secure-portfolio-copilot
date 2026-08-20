import { Link, Outlet } from 'react-router-dom'

export function ApplicationLayout() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand" to="/">
          Secure Portfolio Copilot
        </Link>
        <span className="milestone-label">Foundation · Milestone 0</span>
      </header>
      <main className="page-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        Synthetic-data development environment
      </footer>
    </div>
  )
}
