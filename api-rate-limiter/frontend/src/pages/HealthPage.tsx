import { useEffect, useState } from 'react'
import { getHealth } from '../services/api'
import Spinner from '../components/Spinner'
import { CheckCircle, XCircle, AlertCircle, RefreshCw } from 'lucide-react'
import type { HealthData } from '../types'

export default function HealthPage() {
  const [data, setData]     = useState<HealthData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')

  const load = async () => {
    setLoading(true); setError('')
    try { setData(await getHealth()) }
    catch (e: any) { setError(e.message || 'Health check failed') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const t = setInterval(load, 15000); return () => clearInterval(t) }, [])

  const StatusIcon = ({ status }: { status: string }) => {
    if (status === 'healthy')  return <CheckCircle size={16} className="text-green-400" />
    if (status === 'degraded') return <AlertCircle size={16} className="text-yellow-400" />
    return <XCircle size={16} className="text-red-400" />
  }

  const statusColor = (s: string) =>
    s === 'healthy' ? 'text-green-400' : s === 'degraded' ? 'text-yellow-400' : 'text-red-400'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-white text-xl font-bold">System Health</h2>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-2 bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-2 rounded-lg text-sm transition-colors">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm mb-4">
          {error} — Is the backend running?
        </div>
      )}

      {loading && !data ? <Spinner /> : data && (
        <div className="space-y-4">
          {/* Overall */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-center gap-4">
            <StatusIcon status={data.overall} />
            <div>
              <p className={`font-bold text-lg ${statusColor(data.overall)}`}>{data.overall.toUpperCase()}</p>
              <p className="text-gray-500 text-xs">Gateway: {data.gateway_id} · Uptime: {Math.floor(data.uptime_seconds / 60)}m {Math.floor(data.uptime_seconds % 60)}s</p>
            </div>
          </div>

          {/* Services */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="text-left px-4 py-3">Service</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-right px-4 py-3">Latency</th>
                  <th className="text-left px-4 py-3">Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.services.map(s => (
                  <tr key={s.name} className="border-b border-gray-800/50">
                    <td className="px-4 py-3 text-white font-medium">{s.name}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <StatusIcon status={s.status} />
                        <span className={`text-xs ${statusColor(s.status)}`}>{s.status}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400 text-xs font-mono">
                      {s.latency_ms != null ? `${s.latency_ms.toFixed(1)} ms` : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{s.detail || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
