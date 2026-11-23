import { useEffect, useState } from 'react'
import { getOverview } from '../services/api'
import StatCard from '../components/StatCard'
import Spinner from '../components/Spinner'
import ErrorBox from '../components/ErrorBox'
import type { OverviewStats } from '../types'

const WINDOWS = [
  { label: '5 min',  value: 300 },
  { label: '15 min', value: 900 },
  { label: '1 hr',   value: 3600 },
  { label: '24 hr',  value: 86400 },
]

export default function DashboardPage() {
  const [stats, setStats] = useState<OverviewStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [window, setWindow] = useState(3600)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const load = async () => {
    setLoading(true); setError('')
    try { setStats(await getOverview(window)); setUpdatedAt(new Date()) }
    catch (e: any) { setError(e.message || 'Failed to load') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [window])
  useEffect(() => { const t = setInterval(load, 10000); return () => clearInterval(t) }, [window])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-white text-xl font-bold">Dashboard Overview</h2>
          <p className="text-gray-500 text-xs mt-1">Request volume and gateway performance · refreshes every 10 seconds</p>
        </div>
        <div className="flex gap-2">
          {WINDOWS.map(w => (
            <button key={w.value} onClick={() => setWindow(w.value)}
              className={`px-3 py-1 rounded-lg text-xs transition-colors ${window === w.value ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox message={error} />}
      {loading && !stats ? <Spinner /> : stats && (
        <div>
        {updatedAt && <p className="text-right text-gray-500 text-xs mb-3">Updated {updatedAt.toLocaleTimeString()}</p>}
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          <StatCard label="Total Requests"    value={stats.total_requests.toLocaleString()} />
          <StatCard label="Allowed"           value={stats.allowed_requests.toLocaleString()} color="text-green-400" />
          <StatCard label="Rejected"          value={stats.rejected_requests.toLocaleString()} color="text-red-400" />
          <StatCard label="Rejection Rate"    value={`${stats.total_requests ? (stats.rejected_requests / stats.total_requests * 100).toFixed(1) : '0.0'}%`} color="text-amber-400" />
          <StatCard label="Clients"           value={stats.total_clients} />
          <StatCard label="Active Policies"   value={stats.active_policies} />
          <StatCard label="Req / sec"         value={stats.requests_per_second.toFixed(2)} />
          <StatCard label="Avg Latency"       value={`${stats.avg_latency_ms.toFixed(1)} ms`} />
          <StatCard label="p95 Latency"       value={`${stats.p95_latency_ms.toFixed(1)} ms`} />
          <StatCard label="p99 Latency"       value={`${stats.p99_latency_ms.toFixed(1)} ms`} />
        </div>
        <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4"><p className="text-gray-200 text-sm font-medium">How limits work</p><p className="text-gray-500 text-xs mt-1">Each API key is checked against its most specific active policy. Redis shares counters across gateway instances.</p></div>
          <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4"><p className="text-gray-200 text-sm font-medium">Reading the rejection rate</p><p className="text-gray-500 text-xs mt-1">Rejected requests are HTTP 429 responses. A rising rate can mean clients need a higher limit or better backoff.</p></div>
          <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-4"><p className="text-gray-200 text-sm font-medium">Latency percentiles</p><p className="text-gray-500 text-xs mt-1">p95 and p99 show the slower tail of observed request latency for the selected period.</p></div>
        </div>
        </div>
      )}

      {stats && stats.total_requests === 0 && (
        <div className="mt-8 text-center text-gray-600 text-sm">
          No traffic yet. Use the API Console to send requests.
        </div>
      )}
    </div>
  )
}
