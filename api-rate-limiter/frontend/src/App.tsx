import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import AppLayout from './layouts/AppLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import AnalyticsPage from './pages/AnalyticsPage'
import PoliciesPage from './pages/PoliciesPage'
import ClientsPage from './pages/ClientsPage'
import ConsolePage from './pages/ConsolePage'
import HealthPage from './pages/HealthPage'

function ProtectedRoutes() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/"          element={<DashboardPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/policies"  element={<PoliciesPage />} />
        <Route path="/clients"   element={<ClientsPage />} />
        <Route path="/console"   element={<ConsolePage />} />
        <Route path="/health"    element={<HealthPage />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginWithRedirect />} />
          <Route path="/*"     element={<ProtectedRoutes />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

function LoginWithRedirect() {
  const { isAuthenticated } = useAuth()
  if (isAuthenticated) return <Navigate to="/" replace />
  return <LoginPage />
}
