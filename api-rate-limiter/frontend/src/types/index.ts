export type Algorithm = 'fixed_window' | 'sliding_window' | 'token_bucket'
export type ClientTier = 'basic' | 'premium'

export interface Client {
  id: string
  name: string
  tier: ClientTier
  enabled: boolean
  created_at: number
  key_prefix: string
  total_requests?: number
  rejected_requests?: number
}

export interface ClientCreateResponse extends Client {
  api_key: string
}

export interface Policy {
  id: string
  client_id: string | null
  method: string | null
  route: string | null
  algorithm: Algorithm
  limit: number
  window: number
  bucket_capacity: number | null
  refill_rate: number | null
  enabled: boolean
  created_at: number
  updated_at: number
}

export interface OverviewStats {
  total_requests: number
  allowed_requests: number
  rejected_requests: number
  total_clients: number
  active_policies: number
  requests_per_second: number
  avg_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
}

export interface TimeSeriesPoint {
  timestamp: number
  total: number
  allowed: number
  rejected: number
}

export interface RouteStats {
  route: string
  total: number
  allowed: number
  rejected: number
}

export interface ClientStats {
  client_id: string
  client_name: string
  total: number
  rejected: number
}

export interface AnalyticsData {
  time_series: TimeSeriesPoint[]
  by_route: RouteStats[]
  by_client: ClientStats[]
  by_algorithm: Record<string, number>
}

export interface ServiceHealth {
  name: string
  status: 'healthy' | 'degraded' | 'down'
  latency_ms?: number
  detail?: string
}

export interface HealthData {
  overall: string
  gateway_id: string
  uptime_seconds: number
  services: ServiceHealth[]
}
