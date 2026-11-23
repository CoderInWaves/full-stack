import { NavLink } from 'react-router-dom'
import { LayoutDashboard, BarChart2, Shield, Users, Terminal, Activity, LogOut } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

const links = [
  { to: '/',          label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/analytics', label: 'Analytics',   icon: BarChart2 },
  { to: '/policies',  label: 'Policies',    icon: Shield },
  { to: '/clients',   label: 'Clients',     icon: Users },
  { to: '/console',   label: 'API Console', icon: Terminal },
  { to: '/health',    label: 'Health',      icon: Activity },
]

export default function Sidebar() {
  const { logout } = useAuth()
  return (
    <aside className="w-56 min-h-screen bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="px-5 py-5 border-b border-gray-800">
        <p className="text-xs text-gray-500 uppercase tracking-widest">Rate Limiter</p>
        <h1 className="text-white font-bold text-lg">Admin Dashboard</h1>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-2">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <Icon size={16} />{label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-gray-800">
        <button onClick={logout}
          className="flex items-center gap-2 text-gray-400 hover:text-white text-sm px-3 py-2 w-full rounded-lg hover:bg-gray-800 transition-colors">
          <LogOut size={16} /> Logout
        </button>
      </div>
    </aside>
  )
}
