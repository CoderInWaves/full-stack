import { useEffect, useState } from 'react'
import { getPolicies, createPolicy, updatePolicy, deletePolicy } from '../services/api'
import Spinner from '../components/Spinner'
import ErrorBox from '../components/ErrorBox'
import Toast from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'
import type { Policy } from '../types'
import { Plus, Pencil, Trash2, ToggleLeft, ToggleRight } from 'lucide-react'

const ALGOS = ['sliding_window', 'fixed_window', 'token_bucket']
const blank = { client_id: '', method: '', route: '', algorithm: 'sliding_window', limit: 10, window: 60, bucket_capacity: '', refill_rate: '', enabled: true }

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<Policy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Policy | null>(null)
  const [form, setForm] = useState<any>(blank)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setPolicies(await getPolicies()) }
    catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const openCreate = () => { setEditing(null); setForm(blank); setShowForm(true) }
  const openEdit = (p: Policy) => {
    setEditing(p)
    setForm({ ...p, bucket_capacity: p.bucket_capacity ?? '', refill_rate: p.refill_rate ?? '' })
    setShowForm(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const payload = {
      ...form,
      client_id:       form.client_id || null,
      method:          form.method || null,
      route:           form.route || null,
      bucket_capacity: form.bucket_capacity ? Number(form.bucket_capacity) : null,
      refill_rate:     form.refill_rate ? Number(form.refill_rate) : null,
      limit:           Number(form.limit),
      window:          Number(form.window),
    }
    try {
      if (editing) await updatePolicy(editing.id, payload)
      else await createPolicy(payload)
      setToast({ msg: editing ? 'Policy updated' : 'Policy created', type: 'success' })
      setShowForm(false)
      load()
    } catch (e: any) {
      setToast({ msg: e.message || 'Failed', type: 'error' })
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deletePolicy(id)
      setToast({ msg: 'Policy deleted', type: 'success' })
      load()
    } catch { setToast({ msg: 'Delete failed', type: 'error' }) }
    setConfirmDelete(null)
  }

  const handleToggle = async (p: Policy) => {
    try {
      await updatePolicy(p.id, { enabled: !p.enabled })
      setToast({ msg: `Policy ${p.enabled ? 'disabled' : 'enabled'}`, type: 'success' })
      load()
    } catch { setToast({ msg: 'Update failed', type: 'error' }) }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-white text-xl font-bold">Rate-Limit Policies</h2>
        <button onClick={openCreate}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm transition-colors">
          <Plus size={15} /> New Policy
        </button>
      </div>

      {error && <ErrorBox message={error} />}
      {loading ? <Spinner /> : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          {policies.length === 0 ? (
            <p className="text-gray-600 text-sm text-center py-10">No policies yet. Create one to get started.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800 bg-gray-900/80">
                  {['Client', 'Method', 'Route', 'Algorithm', 'Limit', 'Window', 'Status', ''].map(h => (
                    <th key={h} className="text-left px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {policies.map(p => (
                  <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-3 text-gray-300">{p.client_id || <span className="text-gray-600">global</span>}</td>
                    <td className="px-4 py-3 text-gray-400">{p.method || '*'}</td>
                    <td className="px-4 py-3 text-gray-400">{p.route || '*'}</td>
                    <td className="px-4 py-3"><span className="bg-indigo-900/50 text-indigo-300 px-2 py-0.5 rounded text-xs">{p.algorithm}</span></td>
                    <td className="px-4 py-3 text-gray-300">{p.limit}</td>
                    <td className="px-4 py-3 text-gray-400">{p.window}s</td>
                    <td className="px-4 py-3">
                      <button onClick={() => handleToggle(p)}>
                        {p.enabled
                          ? <ToggleRight size={20} className="text-green-400" />
                          : <ToggleLeft size={20} className="text-gray-600" />}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        <button onClick={() => openEdit(p)} className="text-gray-500 hover:text-white"><Pencil size={14} /></button>
                        <button onClick={() => setConfirmDelete(p.id)} className="text-gray-500 hover:text-red-400"><Trash2 size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-lg shadow-2xl">
            <h3 className="text-white font-semibold mb-4">{editing ? 'Edit Policy' : 'New Policy'}</h3>
            <form onSubmit={handleSubmit} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Client ID (blank = global)', key: 'client_id', type: 'text' },
                  { label: 'Method (blank = all)', key: 'method', type: 'text' },
                  { label: 'Route (blank = all)', key: 'route', type: 'text' },
                  { label: 'Limit', key: 'limit', type: 'number' },
                  { label: 'Window (seconds)', key: 'window', type: 'number' },
                  { label: 'Bucket Capacity', key: 'bucket_capacity', type: 'number' },
                  { label: 'Refill Rate (tokens/s)', key: 'refill_rate', type: 'number' },
                ].map(f => (
                  <div key={f.key}>
                    <label className="block text-xs text-gray-400 mb-1">{f.label}</label>
                    <input type={f.type} value={form[f.key]} onChange={e => setForm({ ...form, [f.key]: e.target.value })}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500" />
                  </div>
                ))}
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Algorithm</label>
                  <select value={form.algorithm} onChange={e => setForm({ ...form, algorithm: e.target.value })}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
                    {ALGOS.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button type="button" onClick={() => setShowForm(false)}
                  className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700">Cancel</button>
                <button type="submit"
                  className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">
                  {editing ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          message="Delete this policy? This cannot be undone."
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  )
}
