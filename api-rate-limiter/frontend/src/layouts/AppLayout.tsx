import Sidebar from './Sidebar'
import { Outlet } from 'react-router-dom'

export default function AppLayout() {
  return (
    <div className="flex min-h-screen bg-gray-950">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
