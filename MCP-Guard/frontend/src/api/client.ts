export type RequestOptions = RequestInit & { allowStatuses?: number[] };

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

let adminToken = '';
let unauthorizedHandler: (() => void) | undefined;

export function setAdminToken(token: string) {
  adminToken = token;
}

export function setUnauthorizedHandler(handler: () => void) {
  unauthorizedHandler = handler;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { allowStatuses = [], headers, ...init } = options;
  let response: Response;
  try {
    response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(adminToken ? { Authorization: `Bearer ${adminToken}` } : {}),
        ...headers,
      },
      cache: 'no-store',
    });
  } catch {
    throw new ApiError('Could not reach MCP-Guard. Check that the gateway is running.', 0, null);
  }

  const isText = response.headers.get('content-type')?.includes('text/plain');
  const payload: unknown = isText
    ? await response.text()
    : await response.json().catch(() => ({}));
  if (response.status === 401 && adminToken) unauthorizedHandler?.();
  if (!response.ok && !allowStatuses.includes(response.status)) {
    const message =
      typeof payload === 'object' && payload !== null && 'error' in payload
        ? String((payload as { error: unknown }).error)
        : `Request failed with HTTP ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export const api = {
  session: () => request<AdminSession>('/admin/session'),
  readiness: () => request<Readiness>('/health/ready', { allowStatuses: [503] }),
  metrics: () => request<string>('/metrics'),
  agents: () => request<{ agents: Agent[] }>('/admin/agents'),
  servers: () => request<{ servers: McpServer[] }>('/admin/servers'),
  policy: () => request<PolicySnapshot>('/admin/policy'),
  savePolicy: (policy: unknown) =>
    request<{ version: number; status: string }>('/admin/policy', {
      method: 'PUT',
      body: JSON.stringify({ policy }),
    }),
  rollbackPolicy: (version: number) =>
    request<{ version: number; rolled_back_to: number }>(`/admin/policy/rollback/${version}`, {
      method: 'POST',
      body: '{}',
    }),
  approvals: (state: string) =>
    request<{ approvals: Approval[] }>(`/admin/approvals?state=${encodeURIComponent(state)}`),
  decideApproval: (id: string, decision: 'approve' | 'reject') =>
    request<Approval>(`/admin/approvals/${encodeURIComponent(id)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  audit: (params: URLSearchParams) =>
    request<AuditResponse>(`/admin/audit?${params.toString()}`),
  dlp: () => request<DlpConfig>('/admin/dlp'),
  settings: () => request<Settings>('/admin/settings'),
};

export interface AdminSession {
  administrator_id: string;
  roles: string[];
}
export interface Readiness {
  status: 'ready' | 'not_ready';
  upstream_configured: boolean;
  upstream_status: 'unknown' | 'available' | 'unavailable';
  policy_engine: string;
  dlp_engine: string;
}
export interface Agent {
  id: string;
  name: string;
  enabled: boolean;
  tenant_ids: string[];
  roles: string[];
  servers: string[];
  authentication_configured: boolean;
  last_activity: string | null;
}
export interface McpServer {
  name: string;
  transport: 'http' | 'stdio' | 'unknown';
  endpoint: string;
  assigned_agents: string[];
  status: 'healthy' | 'unavailable' | 'unknown';
}
export interface PolicySnapshot {
  version: number;
  policy: {
    default_action: string;
    agents: Record<string, AgentPolicy>;
  };
  history: PolicyVersion[];
}
export interface AgentPolicy {
  servers?: Record<string, ServerPolicy>;
  tenant_ids?: string[];
  user_ids?: string[];
  roles?: string[];
}
export interface ServerPolicy {
  enabled?: boolean;
  tools?: Record<string, ToolRule>;
  resources?: Record<string, ToolRule>;
  prompts?: Record<string, ToolRule>;
  methods?: Record<string, string>;
}
export interface ToolRule {
  action: string;
  tenant_ids?: string[];
  user_ids?: string[];
  roles?: string[];
  argument_constraints?: unknown;
}
export interface PolicyVersion {
  version: number;
  created_at: string;
  action: string;
  actor: string;
}
export interface Approval {
  approval_id: string;
  agent_id: string;
  tenant_id: string;
  user_id: string;
  server: string;
  tool: string;
  state: string;
  created_at: string;
  expires_at: string;
  approver_id: string | null;
  decided_at: string | null;
  consumed: boolean;
}
export interface AuditEvent {
  timestamp: string;
  agent_id?: string;
  tenant_id?: string;
  user_id?: string;
  server?: string;
  method?: string;
  tool?: string;
  decision?: string;
  reason_code?: string;
  correlation_id?: string;
  request_id?: string;
  latency_ms?: number;
}
export interface AuditResponse {
  events: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  truncated: boolean;
  source: string;
}
export interface DlpRule {
  name: string;
  pattern: string;
  action: 'block' | 'redact';
  replacement: string;
  enabled: boolean;
  agents: string[];
  tenants: string[];
  users: string[];
  servers: string[];
  methods: string[];
  directions: string[];
}
export interface DlpConfig {
  enabled: boolean;
  runtime_editing_supported: boolean;
  rules: DlpRule[];
}
export interface Settings {
  product: string;
  environment: string;
  gateway_transport: string;
  listener: { host: string; port: number } | null;
  allowed_origins: string[];
  jwt_enabled: boolean;
  mtls_enabled: boolean;
  mtls_required: boolean;
  tls_server_certificate_configured: boolean;
  security: {
    max_message_size: number;
    request_timeout_seconds: number;
    approval_timeout_seconds: number;
    dlp_enabled: boolean;
  };
  audit: {
    enabled: boolean;
    max_size_mb: number;
    backup_count: number;
    payload_logging_enabled: boolean;
    retention_days: number | null;
  };
  configuration_persistence: string;
}
