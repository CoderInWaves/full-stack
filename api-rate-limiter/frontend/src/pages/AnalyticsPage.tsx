import { useEffect, useState } from 'react'
import { getAnalytics } from '../services/api'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid
} from 'recharts'
import Spinner from '../components/Spinner'
import ErrorBox from '../components/ErrorBox'
import type { AnalyticsData } from '../types'

const WINDOWS = [
  { label: '5 min', value: 300 }, { label: '15 min', value: 900 },
  { label: '1 hr',  value: 3600 }, { label: '24 hr', value: 86400 },
]

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [win, setWin] = useState(3600)

  const load = async () => {
    setLoading(true); setError('')
    try { setData(await getAnalytics(win)) }
    catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [win])
  useEffect(() => { const t = setInterval(load, 15000); return () => clearInterval(t) }, [win])

  const tsData = (data?.time_series || []).map(p => ({
    time: new Date(p.timestamp * 1000).toLocaleTimeString(),
    allowed: p.allowed,
    rejected: p.rejected,
    total: p.total,
  }))

  const algoData = Object.entries(data?.by_algorithm || {}).map(([k, v]) => ({ name: k, requests: v }))

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-white text-xl font-bold">Analytics</h2>
        <div className="flex gap-2">
          {WINDOWS.map(w => (
            <button key={w.value} onClick={() => setWin(w.value)}
              className={`px-3 py-1 rounded-lg text-xs transition-colors ${win === w.value ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox message={error} />}
      {loading && !data ? <Spinner /> : (
        <div className="space-y-6">
          {/* Time series */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h3 className="text-white font-semibold mb-4 text-sm">Requests Over Time</h3>
            {tsData.length === 0 ? (
              <p className="text-gray-600 text-sm text-center py-8">No data yet</p>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={tsData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', color: '#f9fafb' }} />
                  <Legend />
                  <Line type="monotone" dataKey="allowed"  stroke="#22c55e" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="rejected" stroke="#ef4444" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* By route */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h3 className="text-white font-semibold mb-4 text-sm">Requests by Route</h3>
              {(data?.by_route || []).length === 0 ? (
                <p className="text-gray-600 text-sm text-center py-8">No data yet</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={data?.by_route || []}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis dataKey="route" tick={{ fill: '#6b7280', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', color: '#f9fafb' }} />
                    <Bar dataKey="allowed"  fill="#22c55e" />
                    <Bar dataKey="rejected" fill="#ef4444" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* By algorithm */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <h3 className="text-white font-semibold mb-4 text-sm">Requests by Algorithm</h3>
              {algoData.length === 0 ? (
                <p className="text-gray-600 text-sm text-center py-8">No data yet</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={algoData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis dataKey="name" tick={{ fill: '#6b7280', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', color: '#f9fafb' }} />
                    <Bar dataKey="requests" fill="#6366f1" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* By client table */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h3 className="text-white font-semibold mb-4 text-sm">Requests by Client</h3>
            {(data?.by_client || []).length === 0 ? (
              <p className="text-gray-600 text-sm text-center py-4">No data yet</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-gray-800">
                    <th className="text-left pb-2">Client</th>
                    <th className="text-right pb-2">Total</th>
                    <th className="text-right pb-2">Rejected</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.by_client.map(c => (
                    <tr key={c.client_id} className="border-b border-gray-800/50">
                      <td className="py-2 text-gray-300">{c.client_name}</td>
                      <td className="py-2 text-right text-gray-300">{c.total}</td>
                      <td className="py-2 text-right text-red-400">{c.rejected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
