import { useState } from 'react'
import { sendTestRequest } from '../services/api'
import { Send, CheckCircle, XCircle } from 'lucide-react'

const ENDPOINTS = [
  { method: 'GET',  path: '/api/products' },
  { method: 'GET',  path: '/api/users' },
  { method: 'POST', path: '/api/orders' },
  { method: 'GET',  path: '/api/health' },
]

export default function ConsolePage() {
  const [method, setMethod]   = useState('GET')
  const [path, setPath]       = useState('/api/products')
  const [apiKey, setApiKey]   = useState('')
  const [body, setBody]       = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState<any>(null)

  const handleSend = async () => {
    if (!apiKey) return
    setLoading(true); setResult(null)
    try {
      const res = await sendTestRequest(method, path, apiKey, body)
      setResult(res)
    } catch (e: any) {
      setResult({ status: 0, data: { error: e.message }, headers: {} })
    } finally { setLoading(false) }
  }

  const isRateLimited = result?.status === 429
  const isAllowed     = result && result.status < 400

  const rlHeaders = result ? {
    'X-RateLimit-Limit':     result.headers['x-ratelimit-limit'],
    'X-RateLimit-Remaining': result.headers['x-ratelimit-remaining'],
    'X-RateLimit-Reset':     result.headers['x-ratelimit-reset'],
    'X-RateLimit-Algorithm': result.headers['x-ratelimit-algorithm'],
    'Retry-After':           result.headers['retry-after'],
    'X-Gateway-ID':          result.headers['x-gateway-id'],
  } : {}

  return (
    <div>
      <h2 className="text-white text-xl font-bold mb-6">API Testing Console</h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Request panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
          <h3 className="text-white font-semibold text-sm">Request</h3>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Quick Select</label>
            <div className="flex flex-wrap gap-2">
              {ENDPOINTS.map(e => (
                <button key={e.path + e.method}
                  onClick={() => { setMethod(e.method); setPath(e.path) }}
                  className={`px-2 py-1 rounded text-xs border transition-colors ${method === e.method && path === e.path ? 'border-indigo-500 bg-indigo-900/40 text-indigo-300' : 'border-gray-700 text-gray-400 hover:border-gray-500'}`}>
                  {e.method} {e.path}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <div className="w-28">
              <label className="block text-xs text-gray-400 mb-1">Method</label>
              <select value={method} onChange={e => setMethod(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
                {['GET','POST','PUT','PATCH','DELETE'].map(m => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div className="flex-1">
              <label className="block text-xs text-gray-400 mb-1">Path</label>
              <input value={path} onChange={e => setPath(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500" />
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">X-API-Key</label>
            <input value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder="rlk_…"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-indigo-500" />
          </div>

          {['POST','PUT','PATCH'].includes(method) && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Body (JSON)</label>
              <textarea value={body} onChange={e => setBody(e.target.value)} rows={4}
                placeholder='{"product_id": 1, "quantity": 2}'
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-indigo-500 resize-none" />
            </div>
          )}

          <button onClick={handleSend} disabled={loading || !apiKey}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-4 py-2 rounded-lg text-sm transition-colors w-full justify-center">
            <Send size={14} /> {loading ? 'Sending…' : 'Send Request'}
          </button>
        </div>

        {/* Response panel */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
          <h3 className="text-white font-semibold text-sm">Response</h3>

          {!result ? (
            <p className="text-gray-600 text-sm text-center py-12">Send a request to see the response</p>
          ) : (
            <>
              <div className="flex items-center gap-3">
                {isRateLimited
                  ? <XCircle size={18} className="text-red-400" />
                  : isAllowed
                    ? <CheckCircle size={18} className="text-green-400" />
                    : <XCircle size={18} className="text-yellow-400" />}
                <span className={`font-mono font-bold text-lg ${isRateLimited ? 'text-red-400' : isAllowed ? 'text-green-400' : 'text-yellow-400'}`}>
                  {result.status}
                </span>
                <span className="text-gray-400 text-sm">
                  {isRateLimited ? '429 Too Many Requests' : isAllowed ? 'OK' : 'Error'}
                </span>
              </div>

              {/* Rate limit headers */}
              <div className="bg-gray-800 rounded-lg p-3 space-y-1">
                <p className="text-xs text-gray-500 mb-2 uppercase tracking-widest">Rate Limit Headers</p>
                {Object.entries(rlHeaders).map(([k, v]) => v && (
                  <div key={k} className="flex justify-between text-xs">
                    <span className="text-gray-500">{k}</span>
                    <span className="text-gray-300 font-mono">{String(v)}</span>
                  </div>
                ))}
              </div>

              {/* Body */}
              <div>
                <p className="text-xs text-gray-500 mb-2 uppercase tracking-widest">Body</p>
                <pre className="bg-gray-800 rounded-lg p-3 text-xs text-gray-300 overflow-auto max-h-48 font-mono">
                  {JSON.stringify(result.data, null, 2)}
                </pre>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
