import { Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { CapabilityRoute } from './auth/CapabilityRoute'
import { ApplicationLayout } from './components/ApplicationLayout'
import { AuthorizedSearchPage } from './pages/AuthorizedSearchPage'
import { ChatPage } from './pages/ChatPage'
import { DocumentIngestionPage } from './pages/DocumentIngestionPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MemoryPage } from './pages/MemoryPage'
import { NotFoundPage } from './pages/NotFoundPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<ApplicationLayout />}>
          <Route index element={<HomePage />} />
          <Route element={<CapabilityRoute capability="QUERY_DOCUMENTS" />}>
            <Route path="chat" element={<ChatPage />} />
            <Route path="memories" element={<MemoryPage />} />
          </Route>
          <Route element={<CapabilityRoute capability="MANAGE_UPLOADS" />}>
            <Route path="admin/documents" element={<DocumentIngestionPage />} />
          </Route>
          {import.meta.env.DEV ? (
            <Route element={<CapabilityRoute capability="QUERY_DOCUMENTS" />}>
              <Route
                path="development/search"
                element={<AuthorizedSearchPage />}
              />
            </Route>
          ) : null}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
