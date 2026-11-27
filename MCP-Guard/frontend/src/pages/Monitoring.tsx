import { useQuery } from '@tanstack/react-query';
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Activity, AlertCircle, Clock3, RefreshCw, ShieldAlert, TrendingUp } from 'lucide-react';
import { api } from '../api/client';
import { MetricCard, PageHeader, Panel, StatusBadge } from '../components/ui';
import { parsePrometheus } from '../utils/metrics';

export function Monitoring() {
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: api.metrics, refetchInterval: 30_000 });
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: api.readiness, refetchInterval: 30_000 });
  const approvals = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => api.approvals('pending'), refetchInterval: 30_000 });
  const snapshot = metrics.data ? parsePrometheus(metrics.data) : null;
  const counters = snapshot ? [
    { name: 'Denied requests', count: snapshot.denied, fill: '#e5484d' },
    { name: 'Auth failures', count: snapshot.authenticationFailures, fill: '#e87e42' },
    { name: 'Upstream errors', count: snapshot.upstreamFailures, fill: '#a16bf2' },
    { name: 'DLP blocks', count: snapshot.dlpBlocks, fill: '#d84266' },
    { name: 'Approval requests', count: snapshot.approvalRequired, fill: '#e2a62e' },
  ] : [];
  const refresh = () => { void metrics.refetch(); void readiness.refetch(); void approvals.refetch(); };

  return (
    <>
      <PageHeader eyebrow="OBSERVABILITY" title="Monitoring" description="In-process gateway counters and health, refreshed every 30 seconds." action={<button className="button button-secondary" onClick={refresh}><RefreshCw size={15} />Refresh</button>} />
      <div className="callout callout-info"><Activity size={17} /><span>The gateway exports counters and a latency histogram, but no timestamped request-rate or trend history. This page does not estimate missing time-series data.</span></div>
      <div className="metric-grid"><MetricCard label="Total requests" value={snapshot?.total ?? '—'} detail="Since this process started" icon={<Activity size={18} />} tone="blue" /><MetricCard label="Request rate" value="Unavailable" detail="No rate gauge or scrape history" icon={<TrendingUp size={18} />} tone="violet" /><MetricCard label="Average latency" value={snapshot?.latencyAverageMs == null ? '—' : `${snapshot.latencyAverageMs.toFixed(1)} ms`} detail="From gateway histogram counters" icon={<Clock3 size={18} />} tone="cyan" /><MetricCard label="Denial rate" value={snapshot && snapshot.total ? `${((snapshot.denied / snapshot.total) * 100).toFixed(1)}%` : snapshot ? '0%' : '—'} detail="Denied / all recorded requests" icon={<ShieldAlert size={18} />} tone="red" /><MetricCard label="Auth failures" value={snapshot?.authenticationFailures ?? '—'} detail="Rejected authentication attempts" icon={<AlertCircle size={18} />} tone="orange" /><MetricCard label="Pending approvals" value={approvals.data?.approvals.length ?? '—'} detail="Current in-memory queue" icon={<Clock3 size={18} />} tone="amber" /></div>
      <div className="overview-grid">
        <Panel title="Security counters" subtitle="Cumulative event counts from Prometheus">
          <div className="chart-area chart-tall">{metrics.isLoading ? <div className="data-state">Loading counters…</div> : metrics.error ? <div className="data-state state-error">{metrics.error.message}</div> : <ResponsiveContainer width="100%" height="100%"><BarChart data={counters} layout="vertical" margin={{ top: 4, right: 18, left: 18, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--line)" /><XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} /><YAxis type="category" dataKey="name" width={110} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} /><Tooltip contentStyle={{ borderRadius: 10, border: '1px solid var(--line)', background: 'var(--surface)' }} /><Bar dataKey="count" name="Count" radius={[0, 4, 4, 0]}>{counters.map((entry) => <Cell key={entry.name} fill={entry.fill} />)}</Bar></BarChart></ResponsiveContainer>}</div>
        </Panel>
        <Panel title="Component status" subtitle="Readiness API and live proxy observations">
          <div className="health-list health-list-large"><div><span><i className="health-marker" />HTTP gateway</span><StatusBadge value={readiness.data?.status ?? 'unknown'} /></div><div><span><i className="health-marker" />Policy engine</span><StatusBadge value={readiness.data?.policy_engine ?? 'unknown'} /></div><div><span><i className="health-marker" />DLP engine</span><StatusBadge value={readiness.data?.dlp_engine ?? 'unknown'} /></div><div><span><i className="health-marker" />Upstream configuration</span><StatusBadge value={readiness.data?.upstream_configured ? 'configured' : readiness.data ? 'not configured' : 'unknown'} /></div><div><span><i className="health-marker" />Upstream connectivity</span><StatusBadge value={readiness.data?.upstream_status ?? 'unknown'} /></div><div><span><i className="health-marker" />STDIO transport</span><StatusBadge value="unknown" /></div></div>
          <p className="chart-note">Upstream status remains unknown until a proxied request checks it. STDIO status has no HTTP health endpoint.</p>
        </Panel>
      </div>
      <Panel title="Available metric families" subtitle="Low-cardinality values intentionally omit agent, tenant, tool and payload labels"><div className="metric-family-grid"><div><strong>mcp_guard_requests_total</strong><small>Allowed, denied, approval-required and redacted requests by bounded MCP method</small></div><div><strong>mcp_guard_request_duration_seconds</strong><small>Latency histogram, count and sum by bounded method</small></div><div><strong>mcp_guard_authentication_failures_total</strong><small>Rejected authentication attempts</small></div><div><strong>mcp_guard_upstream_failures_total</strong><small>Upstream transport errors</small></div><div><strong>mcp_guard_dlp_blocks_total</strong><small>Requests or responses blocked by configured DLP patterns</small></div></div></Panel>
    </>
  );
}
