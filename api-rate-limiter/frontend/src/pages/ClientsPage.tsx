import { useEffect, useState } from 'react'
import { getClients, createClient, updateClient, deleteClient } from '../services/api'
import Spinner from '../components/Spinner'
import ErrorBox from '../components/ErrorBox'
import Toast from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'
import type { Client, ClientCreateResponse } from '../types'
import { Plus, Trash2, ToggleLeft, ToggleRight, Copy, Eye } from 'lucide-react'

export default function ClientsPage() {
  const [clients, setClients] = useState<Client[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', tier: 'basic' })
  const [newKey, setNewKey] = useState<{ client: ClientCreateResponse } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try { setClients(await getClients()) }
    catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const result: ClientCreateResponse = await createClient(form)
      setNewKey({ client: result })
      setShowForm(false)
      setForm({ name: '', tier: 'basic' })
      load()
    } catch (e: any) { setToast({ msg: e.message || 'Failed', type: 'error' }) }
  }

  const handleToggle = async (c: Client) => {
    try {
      await updateClient(c.id, { enabled: !c.enabled })
      setToast({ msg: `Client ${c.enabled ? 'disabled' : 'enabled'}`, type: 'success' })
      load()
    } catch { setToast({ msg: 'Update failed', type: 'error' }) }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteClient(id)
      setToast({ msg: 'Client deleted', type: 'success' })
      load()
    } catch { setToast({ msg: 'Delete failed', type: 'error' }) }
    setConfirmDelete(null)
  }

  const copyKey = (key: string) => {
    navigator.clipboard.writeText(key)
    setToast({ msg: 'API key copied!', type: 'success' })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-white text-xl font-bold">API Clients</h2>
        <button onClick={() => setShowForm(true)}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm transition-colors">
          <Plus size={15} /> New Client
        </button>
      </div>

      {error && <ErrorBox message={error} />}
      {loading ? <Spinner /> : (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          {clients.length === 0 ? (
            <p className="text-gray-600 text-sm text-center py-10">No clients yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  {['Name', 'Tier', 'Key Prefix', 'Status', ''].map(h => (
                    <th key={h} className="text-left px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {clients.map(c => (
                  <tr key={c.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-3 text-white font-medium">{c.name}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${c.tier === 'premium' ? 'bg-yellow-900/50 text-yellow-300' : 'bg-gray-800 text-gray-400'}`}>
                        {c.tier}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-gray-400 text-xs">{c.key_prefix}…</td>
                    <td className="px-4 py-3">
                      <button onClick={() => handleToggle(c)}>
                        {c.enabled
                          ? <ToggleRight size={20} className="text-green-400" />
                          : <ToggleLeft size={20} className="text-gray-600" />}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <button onClick={() => setConfirmDelete(c.id)} className="text-gray-500 hover:text-red-400">
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-80 shadow-2xl">
            <h3 className="text-white font-semibold mb-4">New Client</h3>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Name</label>
                <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Tier</label>
                <select value={form.tier} onChange={e => setForm({ ...form, tier: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
                  <option value="basic">Basic</option>
                  <option value="premium">Premium</option>
                </select>
              </div>
              <div className="flex gap-3 justify-end pt-2">
                <button type="button" onClick={() => setShowForm(false)}
                  className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700">Cancel</button>
                <button type="submit"
                  className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Show new API key once */}
      {newKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-green-700 rounded-xl p-6 w-96 shadow-2xl">
            <div className="flex items-center gap-2 mb-3">
              <Eye size={16} className="text-green-400" />
              <h3 className="text-white font-semibold">API Key Created</h3>
            </div>
            <p className="text-gray-400 text-xs mb-3">Copy this key now — it will not be shown again.</p>
            <div className="bg-gray-800 rounded-lg px-3 py-2 font-mono text-green-300 text-xs break-all mb-4">
              {newKey.client.api_key}
            </div>
            <div className="flex gap-3">
              <button onClick={() => copyKey(newKey.client.api_key)}
                className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-green-700 text-white hover:bg-green-600">
                <Copy size={14} /> Copy Key
              </button>
              <button onClick={() => setNewKey(null)}
                className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700">Done</button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          message="Delete this client? Their API key will stop working immediately."
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  )
}
