import { useQuery } from '@tanstack/react-query';
import {
  Activity, ArrowDownRight, ArrowUpRight, CheckCircle2, Clock3, Network, ShieldAlert,
  ShieldCheck, Users,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api/client';
import { Button, DataState, MetricCard, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';
import { groupAuditByAgent, groupAuditByHour, groupDeniedTools, parsePrometheus } from '../utils/metrics';

const colors = ['#2563eb', '#f04452', '#f59f0b', '#1aa780', '#875bf7'];

export function Overview() {
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: api.metrics, refetchInterval: 30_000 });
  const health = useQuery({ queryKey: ['readiness'], queryFn: api.readiness, refetchInterval: 30_000 });
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.agents });
  const servers = useQuery({ queryKey: ['servers'], queryFn: api.servers });
  const approvals = useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => api.approvals('pending'), refetchInterval: 30_000 });
  const auditParams = new URLSearchParams({ limit: '200', offset: '0' });
  const audit = useQuery({ queryKey: ['audit', 'overview'], queryFn: () => api.audit(auditParams) });
  const snapshot = metrics.data ? parsePrometheus(metrics.data) : null;
  const eventRows = audit.data?.events ?? [];
  const hourData = groupAuditByHour(eventRows);
  const agentData = groupAuditByAgent(eventRows);
  const deniedToolData = groupDeniedTools(eventRows);
  const decisions = snapshot ? [
    { name: 'Allowed', value: snapshot.allowed },
    { name: 'Denied', value: snapshot.denied },
    { name: 'Approval required', value: snapshot.approvalRequired },
  ].filter((item) => item.value > 0) : [];

  return (
    <>
      <PageHeader eyebrow="SECURITY OVERVIEW" title="Good morning" description="A live view of requests, policy decisions and gateway health." action={<Button variant="secondary" onClick={() => { void metrics.refetch(); void health.refetch(); void audit.refetch(); }}>↻&nbsp; Refresh data</Button>} />
      <div className="metric-grid">
        <MetricCard label="Agent requests" value={snapshot?.total ?? '—'} detail="Since gateway process started" icon={<Activity size={18} />} tone="blue" />
        <MetricCard label="Allowed" value={snapshot?.allowed ?? '—'} detail="Requests permitted by policy" icon={<CheckCircle2 size={18} />} tone="green" />
        <MetricCard label="Denied" value={snapshot?.denied ?? '—'} detail="Requests denied by policy" icon={<ShieldAlert size={18} />} tone="red" />
        <MetricCard label="Pending approvals" value={approvals.data?.approvals.length ?? '—'} detail="Waiting for an administrator" icon={<Clock3 size={18} />} tone="amber" />
        <MetricCard label="Active agents" value={agents.data?.agents.filter((agent) => agent.enabled).length ?? '—'} detail="Configured and enabled" icon={<Users size={18} />} tone="violet" />
        <MetricCard label="Connected servers" value={servers.data?.servers.filter((server) => server.status === 'healthy').length ?? '—'} detail="Connectivity reported healthy" icon={<Network size={18} />} tone="cyan" />
        <MetricCard label="DLP blocks" value={snapshot?.dlpBlocks ?? '—'} detail="Blocked by configured patterns" icon={<ShieldCheck size={18} />} tone="orange" />
        <MetricCard label="System health" value={health.data?.status === 'ready' ? 'Ready' : health.data?.status === 'not_ready' ? 'Not ready' : '—'} detail="Gateway readiness endpoint" icon={<Activity size={18} />} tone="green" />
      </div>

      <div className="overview-grid">
        <Panel title="Agent request activity" subtitle="Requests represented by the latest 200 audit records">
          <div className="chart-area chart-tall"><DataState loading={audit.isLoading} error={audit.error} onRetry={() => void audit.refetch()}>
            <ResponsiveContainer width="100%" height="100%"><BarChart data={hourData} margin={{ top: 8, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--line)" /><XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} /><Tooltip contentStyle={{ borderRadius: 10, border: '1px solid var(--line)', background: 'var(--surface)' }} /><Bar dataKey="requests" name="Audit events" fill="#3168ef" radius={[4, 4, 0, 0]} barSize={20} />
            </BarChart></ResponsiveContainer>
          </DataState></div>
          {audit.data?.truncated && <small className="chart-note">Audit source exceeds the bounded window; this view may be incomplete.</small>}
        </Panel>
        <Panel title="Policy decisions" subtitle="Actual in-process counters since startup">
          <div className="chart-area chart-tall"><DataState loading={metrics.isLoading} error={metrics.error} onRetry={() => void metrics.refetch()}>
            {decisions.length ? <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={decisions} dataKey="value" nameKey="name" innerRadius={62} outerRadius={92} paddingAngle={3} stroke="none">{decisions.map((entry, index) => <Cell key={entry.name} fill={colors[index]} />)}</Pie><Tooltip contentStyle={{ borderRadius: 10, border: '1px solid var(--line)', background: 'var(--surface)' }} /><Legend verticalAlign="bottom" iconType="circle" wrapperStyle={{ fontSize: 11 }} /></PieChart></ResponsiveContainer> : <div className="chart-empty"><span>No request counters yet</span></div>}
          </DataState></div>
        </Panel>
      </div>

      <div className="overview-grid overview-grid-three">
        <Panel title="Top agents" subtitle="From recent payload-free audit records"><DataState loading={audit.isLoading} error={audit.error} empty={!agentData.length} onRetry={() => void audit.refetch()}>{agentData.map((item, index) => <div className="rank-row" key={item.name}><span className="rank-number">0{index + 1}</span><strong>{item.name}</strong><span className="rank-value">{item.value} <small>events</small></span><div className="rank-bar"><i style={{ width: `${Math.max(8, (item.value / (agentData[0]?.value || 1)) * 100)}%` }} /></div></div>)}</DataState><small className="chart-note">Latest 200 records only. Audit history may be limited.</small></Panel>
        <Panel title="Most denied tools" subtitle="Based on recent audit records"><DataState loading={audit.isLoading} error={audit.error} empty={!deniedToolData.length} onRetry={() => void audit.refetch()}>{deniedToolData.map((item, index) => <div className="rank-row" key={item.name}><span className="rank-number rank-danger">0{index + 1}</span><strong>{item.name}</strong><span className="rank-value">{item.value} <small>denied</small></span><div className="rank-bar rank-bar-red"><i style={{ width: `${Math.max(8, (item.value / (deniedToolData[0]?.value || 1)) * 100)}%` }} /></div></div>)}</DataState><small className="chart-note">Derived only from currently available audit events.</small></Panel>
        <Panel title="Security counters" subtitle="Aggregated counters from the gateway">
          <div className="counter-list"><div><span><ArrowUpRight size={15} />Authentication failures</span><strong>{snapshot?.authenticationFailures ?? '—'}</strong></div><div><span><ArrowDownRight size={15} />Upstream failures</span><strong>{snapshot?.upstreamFailures ?? '—'}</strong></div><div><span><ShieldAlert size={15} />DLP blocks</span><strong>{snapshot?.dlpBlocks ?? '—'}</strong></div><div><span><Clock3 size={15} />Average latency</span><strong>{snapshot?.latencyAverageMs == null ? '—' : `${snapshot.latencyAverageMs.toFixed(1)} ms`}</strong></div></div>
        </Panel>
      </div>

      <div className="overview-grid">
        <Panel title="Recent security activity" subtitle="Payloads are excluded from this table" action={<a className="text-link" href="#/audit">View audit logs →</a>}>
          <DataState loading={audit.isLoading} error={audit.error} empty={!eventRows.length} onRetry={() => void audit.refetch()}>
            <Table headers={['Time', 'Agent', 'Action', 'Server', 'Decision', 'Request ID']}>
              {eventRows.slice(0, 6).map((event, index) => <tr key={`${event.timestamp}-${event.request_id ?? index}`}><td>{formatDate(event.timestamp)}</td><td className="cell-strong">{event.agent_id || '—'}</td><td>{event.tool || event.method || '—'}</td><td>{event.server || '—'}</td><td><StatusBadge value={event.decision || 'unknown'} /></td><td className="mono">{event.request_id || event.correlation_id || '—'}</td></tr>)}
            </Table>
          </DataState>
        </Panel>
        <Panel title="Gateway health" subtitle="Current component readiness">
          <div className="health-list"><div><span><i className="health-marker" />MCP gateway</span><StatusBadge value={health.data?.status ?? 'unknown'} /></div><div><span><i className="health-marker" />HTTP transport</span><StatusBadge value={health.data ? 'healthy' : 'unknown'} /></div><div><span><i className="health-marker" />STDIO transport</span><StatusBadge value="unknown" /></div><div><span><i className="health-marker" />Policy engine</span><StatusBadge value={health.data?.policy_engine ?? 'unknown'} /></div><div><span><i className="health-marker" />DLP engine</span><StatusBadge value={health.data?.dlp_engine ?? 'unknown'} /></div><div><span><i className="health-marker" />Upstream connection</span><StatusBadge value={health.data?.upstream_status ?? 'unknown'} /></div></div>
          <p className="chart-note">STDIO transport health is not exposed by the HTTP gateway.</p>
        </Panel>
      </div>
    </>
  );
}
