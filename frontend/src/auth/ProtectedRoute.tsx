import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './useAuth'

export function ProtectedRoute() {
  const auth = useAuth()
  const location = useLocation()

  if (auth.status === 'loading') {
    return <p role="status">Validating session…</p>
  }
  if (auth.status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
