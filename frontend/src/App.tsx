import { Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { CapabilityRoute } from './auth/CapabilityRoute'
import { ApplicationLayout } from './components/ApplicationLayout'
import { DocumentIngestionPage } from './pages/DocumentIngestionPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<ApplicationLayout />}>
          <Route index element={<HomePage />} />
          <Route element={<CapabilityRoute capability="MANAGE_UPLOADS" />}>
            <Route path="admin/documents" element={<DocumentIngestionPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
