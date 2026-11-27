import { createContext, lazy, Suspense, useContext, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { setAdminToken, setUnauthorizedHandler } from './api/client';
import type { AdminSession } from './api/client';
import { AdminLayout } from './components/AdminLayout';
import { Login } from './pages/Login';

const Overview = lazy(() => import('./pages/Overview').then((module) => ({ default: module.Overview })));
const Agents = lazy(() => import('./pages/Agents').then((module) => ({ default: module.Agents })));
const Servers = lazy(() => import('./pages/Servers').then((module) => ({ default: module.Servers })));
const Policies = lazy(() => import('./pages/Policies').then((module) => ({ default: module.Policies })));
const Approvals = lazy(() => import('./pages/Approvals').then((module) => ({ default: module.Approvals })));
const AuditLogs = lazy(() => import('./pages/AuditLogs').then((module) => ({ default: module.AuditLogs })));
const Dlp = lazy(() => import('./pages/Dlp').then((module) => ({ default: module.Dlp })));
const Monitoring = lazy(() => import('./pages/Monitoring').then((module) => ({ default: module.Monitoring })));
const Integrations = lazy(() => import('./pages/Integrations').then((module) => ({ default: module.Integrations })));
const SettingsPage = lazy(() => import('./pages/Settings').then((module) => ({ default: module.SettingsPage })));

interface AuthContextValue {
  session: AdminSession | null;
  login: (session: AdminSession, token: string) => void;
  logout: () => void;
}
const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside the application');
  return context;
}

function Protected({ children }: PropsWithChildren) {
  const { session } = useAuth();
  return session ? children : <Navigate to="/login" replace />;
}

export function App({ queryClient }: { queryClient: QueryClient }) {
  const [session, setSession] = useState<AdminSession | null>(null);
  const auth = useMemo<AuthContextValue>(
    () => ({
      session,
      login: (nextSession, token) => {
        setAdminToken(token);
        setSession(nextSession);
        queryClient.clear();
      },
      logout: () => {
        setAdminToken('');
        setSession(null);
        queryClient.clear();
      },
    }),
    [queryClient, session],
  );

  useEffect(() => {
    setUnauthorizedHandler(auth.logout);
    return () => setUnauthorizedHandler(() => undefined);
  }, [auth.logout]);

  return (
    <AuthContext.Provider value={auth}>
      <HashRouter>
        <Routes>
          <Route path="/login" element={session ? <Navigate to="/" replace /> : <Login />} />
          <Route
            path="/"
            element={
              <Protected>
                <AdminLayout />
              </Protected>
            }
          >
            <Route index element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Overview /></Suspense>} />
            <Route path="agents" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Agents /></Suspense>} />
            <Route path="servers" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Servers /></Suspense>} />
            <Route path="policies" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Policies /></Suspense>} />
            <Route path="approvals" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Approvals /></Suspense>} />
            <Route path="audit" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><AuditLogs /></Suspense>} />
            <Route path="dlp" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Dlp /></Suspense>} />
            <Route path="monitoring" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Monitoring /></Suspense>} />
            <Route path="integrations" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><Integrations /></Suspense>} />
            <Route path="settings" element={<Suspense fallback={<div className="data-state">Loading console…</div>}><SettingsPage /></Suspense>} />
          </Route>
          <Route path="*" element={<Navigate to={session ? '/' : '/login'} replace />} />
        </Routes>
      </HashRouter>
    </AuthContext.Provider>
  );
}
