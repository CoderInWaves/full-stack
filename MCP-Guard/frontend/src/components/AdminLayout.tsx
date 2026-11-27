import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AppWindow, Bell, Bot, Boxes, ChevronLeft, CircleHelp, ClipboardCheck, FileClock,
  Gauge, LayoutDashboard, LockKeyhole, LogOut, Menu, Moon, Network, Search, Settings,
  Shield, ShieldAlert, Sun, X,
} from 'lucide-react';
import { api } from '../api/client';
import { useAuth } from '../App';
import { StatusBadge } from './ui';

const navigation = [
  { label: 'Overview', path: '/', icon: LayoutDashboard },
  { label: 'Agents', path: '/agents', icon: Bot },
  { label: 'MCP servers', path: '/servers', icon: Network },
  { label: 'Policies', path: '/policies', icon: Shield },
  { label: 'Approvals', path: '/approvals', icon: ClipboardCheck },
  { label: 'Audit logs', path: '/audit', icon: FileClock },
  { label: 'DLP', path: '/dlp', icon: ShieldAlert },
  { label: 'Monitoring', path: '/monitoring', icon: Gauge },
  { label: 'Integrations', path: '/integrations', icon: Boxes },
  { label: 'Settings', path: '/settings', icon: Settings },
];

export function AdminLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const health = useQuery({ queryKey: ['readiness'], queryFn: api.readiness, refetchInterval: 30_000 });
  const approvals = useQuery({
    queryKey: ['approvals', 'pending'],
    queryFn: () => api.approvals('pending'),
    refetchInterval: 30_000,
  });
  const current = navigation.find((item) => item.path === location.pathname)?.label ?? 'Overview';
  const matches = navigation.filter((item) => item.label.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className={`app-shell ${dark ? 'theme-dark' : ''}`}>
      {mobileOpen && <button className="mobile-overlay" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><Shield size={19} strokeWidth={2.4} /></div>
          <div className="brand-copy"><strong>MCP<span>-</span>Guard</strong><small>SECURITY CONSOLE</small></div>
          <button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={18} /></button>
        </div>
        <div className="workspace-chip"><span className="workspace-dot" />Local gateway<span className="workspace-caret">⌄</span></div>
        <p className="nav-label">WORKSPACE</p>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map(({ label, path, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}
            >
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {label === 'Approvals' && Boolean(approvals.data?.approvals.length) && <em>{approvals.data?.approvals.length}</em>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-help"><div className="help-icon"><CircleHelp size={17} /></div><div><strong>Need a hand?</strong><small>Explore the MCP-Guard docs</small></div><ChevronLeft size={14} className="help-arrow" /></div>
          <div className="sidebar-user"><div className="avatar">{session?.administrator_id.slice(0, 1).toUpperCase() || 'A'}</div><div className="user-copy"><strong>{session?.administrator_id}</strong><small>Administrator</small></div><button className="icon-button" onClick={logout} aria-label="Log out"><LogOut size={16} /></button></div>
        </div>
      </aside>

      <main className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-toggle" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
            <div className="breadcrumbs"><span>Workspace</span><span className="crumb-divider">/</span><strong>{current}</strong></div>
          </div>
          <div className="topbar-actions">
            <div className="global-search">
              <Search size={16} />
              <input aria-label="Search pages" placeholder="Search pages..." value={search} onFocus={() => setSearchOpen(true)} onChange={(event) => { setSearch(event.target.value); setSearchOpen(true); }} onKeyDown={(event) => { if (event.key === 'Enter' && matches[0]) { navigate(matches[0].path); setSearchOpen(false); setSearch(''); } }} />
              <kbd>⌘ K</kbd>
              {searchOpen && search && <div className="search-results">{matches.length ? matches.map((item) => <button key={item.path} onClick={() => { navigate(item.path); setSearchOpen(false); setSearch(''); }}><item.icon size={15} />{item.label}</button>) : <span>No pages found</span>}</div>}
            </div>
            <div className="top-health"><span className="health-label">Gateway</span><StatusBadge value={health.data?.status === 'ready' ? 'Healthy' : health.data?.status === 'not_ready' ? 'Not ready' : 'Checking'} /></div>
            <button className="icon-button top-icon" aria-label="Open approvals" title="Open approvals" onClick={() => navigate('/approvals')}><Bell size={17} />{Boolean(approvals.data?.approvals.length) && <i />}</button>
            <button className="icon-button top-icon" aria-label={dark ? 'Use light theme' : 'Use dark theme'} onClick={() => setDark((value) => !value)}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button>
          </div>
        </header>
        <div className="page-content"><Outlet /></div>
        <footer className="app-footer"><span><LockKeyhole size={13} /> Admin actions are checked by the MCP-Guard backend</span><span><AppWindow size={13} /> MCP-Guard Console</span></footer>
      </main>
    </div>
  );
}
