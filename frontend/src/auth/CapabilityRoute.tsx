import { Navigate, Outlet } from 'react-router-dom'

import { hasCapability } from './capabilities'
import { useAuth } from './useAuth'
import type { Capability } from '../types/auth'

export function CapabilityRoute({ capability }: { capability: Capability }) {
  const auth = useAuth()
  const grants = auth.currentUser?.authorization_scope.grants ?? []

  if (!hasCapability(grants, capability)) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
