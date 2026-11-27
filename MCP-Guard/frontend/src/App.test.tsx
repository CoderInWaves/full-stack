import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

function mockGateway(options: {
  approvals?: Record<string, unknown>[];
  policy?: Record<string, unknown>;
  policyError?: boolean;
  dlpRules?: Record<string, unknown>[];
} = {}) {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith('/admin/session')) return jsonResponse({ administrator_id: 'test-admin', roles: ['admin'] });
    if (path.endsWith('/health/ready')) return jsonResponse({ status: 'ready', upstream_configured: true, upstream_status: 'unknown', policy_engine: 'ok', dlp_engine: 'ok' });
    if (path.endsWith('/metrics')) return new Response('mcp_guard_requests_total{method="tools/call",decision="allowed"} 4\n', { headers: { 'Content-Type': 'text/plain' } });
    if (path.includes('/admin/approvals/') && init?.method === 'POST') {
      const action = JSON.parse(String(init.body)).decision;
      return jsonResponse({ approval_id: path.split('/').at(-2), state: action === 'approve' ? 'approved' : 'rejected' });
    }
    if (path.includes('/admin/approvals')) return jsonResponse({ approvals: options.approvals ?? [] });
    if (path.endsWith('/admin/agents')) return jsonResponse({ agents: [] });
    if (path.endsWith('/admin/servers')) return jsonResponse({ servers: [] });
    if (path.includes('/admin/audit')) return jsonResponse({ events: [], total: 0, limit: 200, offset: 0, has_more: false, truncated: false, source: 'active_file' });
    if (path.endsWith('/admin/policy') && init?.method === 'PUT') {
      return options.policyError
        ? jsonResponse({ error: 'Policy references unknown agent' }, 400)
        : jsonResponse({ version: 2, status: 'active' });
    }
    if (path.endsWith('/admin/policy')) return jsonResponse(options.policy ?? { version: 1, policy: { default_action: 'deny', agents: {} }, history: [] });
    if (path.endsWith('/admin/dlp')) return jsonResponse({ enabled: true, runtime_editing_supported: false, rules: options.dlpRules ?? [] });
    if (path.endsWith('/admin/settings')) return jsonResponse({});
    return jsonResponse({ error: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><App queryClient={queryClient} /></QueryClientProvider>);
}

describe('MCP-Guard admin application', () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    window.location.hash = '';
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('redirects protected pages to the administrator sign-in', () => {
    renderApp();
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(screen.getByLabelText('Administrator token')).toBeInTheDocument();
  });

  it('requires a token before attempting authentication', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    renderApp();
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(await screen.findByText('Enter your administrator token.')).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('authenticates through the backend and navigates to real admin pages', async () => {
    mockGateway();
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'test-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(await screen.findByRole('heading', { name: 'Good morning' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('test-admin')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('link', { name: /Agents/ }));
    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument();
    expect(screen.getByText(/read-only here/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
  });

  it('shows a backend authentication error and does not enter the console', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'Administrator authentication required' }, 401)));
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'bad-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Administrator authentication required');
    expect(screen.queryByRole('heading', { name: 'Good morning' })).not.toBeInTheDocument();
  });

  it('publishes the exact policy JSON through the backend and surfaces validation errors', async () => {
    const fetcher = mockGateway({ policyError: true });
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'test-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await screen.findByRole('heading', { name: 'Good morning' });
    fireEvent.change(screen.getByLabelText('Search pages'), { target: { value: 'Policies' } });
    fireEvent.click(screen.getByRole('button', { name: /^Policies$/ }));
    await screen.findByRole('heading', { name: 'Policies' });
    const editor = await screen.findByLabelText('Active policy JSON');
    fireEvent.change(editor, { target: { value: '{"default_action":"deny","agents":{}}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate & publish' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Policy references unknown agent');
    const update = fetcher.mock.calls.find(([url, init]) => String(url).endsWith('/admin/policy') && init?.method === 'PUT');
    expect(update?.[1]?.body).toBe('{"policy":{"default_action":"deny","agents":{}}}');
  });

  it('requires a confirmation and sends the exact approval ID for a decision', async () => {
    const approval = {
      approval_id: 'exact-approval-71', agent_id: 'agent-1', tenant_id: 'tenant-a', user_id: 'user-a',
      server: 'customer-db', tool: 'delete_customer', state: 'pending', created_at: '2026-11-24T00:00:00Z',
      expires_at: '2026-11-24T00:15:00Z', approver_id: null, decided_at: null, consumed: false,
    };
    const fetcher = mockGateway({ approvals: [approval] });
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'test-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await screen.findByRole('heading', { name: 'Good morning' });
    fireEvent.change(screen.getByLabelText('Search pages'), { target: { value: 'Approvals' } });
    fireEvent.click(screen.getByRole('button', { name: /^Approvals$/ }));
    await screen.findByRole('heading', { name: 'Approval center' });
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    expect(await screen.findByRole('dialog')).toHaveTextContent('exact-approval-71');
    expect(screen.getByRole('dialog')).toHaveTextContent('arguments or a policy reason');
    fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }));
    expect(await screen.findByText('Approve this exact request?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm approve' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => String(url).includes('/admin/approvals/exact-approval-71/decision') && init?.method === 'POST' && init.body === '{"decision":"approve"}')).toBe(true));
  });

  it('applies audit search filters through the audit API', async () => {
    const fetcher = mockGateway();
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'test-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await screen.findByRole('heading', { name: 'Good morning' });
    fireEvent.change(screen.getByLabelText('Search pages'), { target: { value: 'Audit logs' } });
    fireEvent.click(screen.getByRole('button', { name: /^Audit logs$/ }));
    await screen.findByRole('heading', { name: 'Audit logs' });
    fireEvent.change(screen.getByLabelText('Search', { exact: true }), { target: { value: 'req-12' } });
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).includes('/admin/audit?') && String(url).includes('q=req-12'))).toBe(true));
  });

  it('shows configured DLP rules as read-only when runtime editing is unsupported', async () => {
    mockGateway({ dlpRules: [{ name: 'email', pattern: '.+@.+', action: 'redact', replacement: '[MASKED]', enabled: true, agents: [], tenants: [], users: [], servers: [], methods: [], directions: [] }] });
    renderApp();
    fireEvent.change(screen.getByLabelText('Administrator token'), { target: { value: 'test-token' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await screen.findByRole('heading', { name: 'Good morning' });
    fireEvent.change(screen.getByLabelText('Search pages'), { target: { value: 'DLP' } });
    fireEvent.click(screen.getByRole('button', { name: /^DLP$/ }));
    await screen.findByRole('heading', { name: 'DLP rules' });
    expect(await screen.findByText('email')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test a rule' })).toBeDisabled();
    expect(screen.getByText(/Rule updates require a gateway restart/)).toBeInTheDocument();
  });
});
