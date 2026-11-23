import axios from 'axios'

const BASE = '/admin/api/v1'

const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Auth ──────────────────────────────────────────────────────────────────────
export const login = (token: string) =>
  api.post('/auth/login', { token }).then(r => r.data)

// ── Overview ──────────────────────────────────────────────────────────────────
export const getOverview = (window = 3600) =>
  api.get(`/overview?window=${window}`).then(r => r.data)

// ── Analytics ─────────────────────────────────────────────────────────────────
export const getAnalytics = (window = 3600) =>
  api.get(`/analytics?window=${window}`).then(r => r.data)

// ── Health ────────────────────────────────────────────────────────────────────
export const getHealth = () =>
  api.get('/health').then(r => r.data)

// ── Clients ───────────────────────────────────────────────────────────────────
export const getClients = () =>
  api.get('/clients').then(r => r.data)

export const createClient = (data: { name: string; tier: string }) =>
  api.post('/clients', data).then(r => r.data)

export const updateClient = (id: string, data: object) =>
  api.patch(`/clients/${id}`, data).then(r => r.data)

export const deleteClient = (id: string) =>
  api.delete(`/clients/${id}`).then(r => r.data)

// ── Policies ──────────────────────────────────────────────────────────────────
export const getPolicies = () =>
  api.get('/policies').then(r => r.data)

export const createPolicy = (data: object) =>
  api.post('/policies', data).then(r => r.data)

export const updatePolicy = (id: string, data: object) =>
  api.put(`/policies/${id}`, data).then(r => r.data)

export const deletePolicy = (id: string) =>
  api.delete(`/policies/${id}`).then(r => r.data)

// ── Gateway test request ──────────────────────────────────────────────────────
export const sendTestRequest = (
  method: string,
  path: string,
  apiKey: string,
  body?: string
) => {
  const config: any = {
    method,
    url: path,
    headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
    validateStatus: () => true,
  }
  if (body && ['POST', 'PUT', 'PATCH'].includes(method)) {
    try { config.data = JSON.parse(body) } catch { config.data = body }
  }
  return axios(config).then(r => ({
    status: r.status,
    data: r.data,
    headers: r.headers,
  }))
}
