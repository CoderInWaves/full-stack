import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { Shield } from 'lucide-react'

export default function LoginPage() {
  const { login, error } = useAuth()
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try { await login(token) } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 w-full max-w-sm shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="bg-indigo-600 p-2 rounded-lg"><Shield size={20} className="text-white" /></div>
          <div>
            <h1 className="text-white font-bold text-lg">Rate Limiter</h1>
            <p className="text-gray-500 text-xs">Admin Login</p>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Admin Token</label>
            <input
              type="password"
              value={token}
              onChange={e => setToken(e.target.value)}
              placeholder="Enter admin token"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
              required
            />
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button type="submit" disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50">
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
        <p className="text-gray-600 text-xs mt-4 text-center">
          Default dev token: <code className="text-gray-400">dev-admin-token-change-in-production</code>
        </p>
      </div>
    </div>
  )
}
