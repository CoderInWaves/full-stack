import { useQuery } from '@tanstack/react-query';
import { Eye, ShieldAlert, ShieldCheck, Zap } from 'lucide-react';
import { api } from '../api/client';
import { Button, DataState, EmptyNotice, MetricCard, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';

export function Dlp() {
  const config = useQuery({ queryKey: ['dlp'], queryFn: api.dlp });
  const blockedParams = new URLSearchParams({ limit: '50', offset: '0', decision: 'DENY', q: 'DLP_BLOCKED' });
  const activity = useQuery({ queryKey: ['audit', 'dlp-blocks'], queryFn: () => api.audit(blockedParams) });
  const redactRules = config.data?.rules.filter((rule) => rule.action === 'redact').length ?? 0;
  const blockRules = config.data?.rules.filter((rule) => rule.action === 'block').length ?? 0;

  return (
    <>
      <PageHeader eyebrow="DATA PROTECTION" title="DLP rules" description="Review the configured pattern checks applied to MCP request and response content." action={<Button disabled title="DLP configuration is loaded at startup; the backend has no runtime rule mutation endpoint."><Zap size={15} /> Test a rule</Button>} />
      <div className="callout callout-info"><Eye size={17} /><span>Pattern rules are configuration-managed and currently read-only. Regex detection is a limited pattern filter; it is not comprehensive data classification.</span></div>
      <div className="metric-grid metric-grid-three"><MetricCard label="DLP engine" value={config.data?.enabled ? 'Enabled' : config.data ? 'Disabled' : '—'} detail="Runtime component state" icon={<ShieldCheck size={18} />} tone="green" /><MetricCard label="Block rules" value={blockRules} detail="Configured block actions" icon={<ShieldAlert size={18} />} tone="red" /><MetricCard label="Redact rules" value={redactRules} detail="Configured redact actions" icon={<Eye size={18} />} tone="violet" /></div>
      <EmptyNotice title="Rule updates require a gateway restart" body="The DLP endpoint returns active startup configuration only. Creating, editing, disabling, testing or assigning rules is not exposed as an administrative API." />
      <Panel title="Configured DLP rules" subtitle="Patterns are returned to authenticated administrators from the active configuration">
        <DataState loading={config.isLoading} error={config.error} empty={!config.data?.rules.length} onRetry={() => void config.refetch()}>
          <Table headers={['Rule', 'Pattern', 'Scope', 'Direction', 'Action', 'Status']}>
            {config.data?.rules.map((rule) => <tr key={rule.name}><td className="cell-strong">{rule.name}</td><td className="pattern-cell"><code>{rule.pattern}</code></td><td><div className="scope-tags">{rule.agents.map((item) => <span className="mini-chip" key={`a-${item}`}>Agent: {item}</span>)}{rule.tenants.map((item) => <span className="mini-chip" key={`t-${item}`}>Tenant: {item}</span>)}{rule.users.map((item) => <span className="mini-chip" key={`u-${item}`}>User: {item}</span>)}{rule.servers.map((item) => <span className="mini-chip" key={`s-${item}`}>Server: {item}</span>)}{!rule.agents.length && !rule.tenants.length && !rule.users.length && !rule.servers.length && <span className="muted">All configured identities</span>}</div></td><td>{rule.directions.length ? rule.directions.join(', ') : 'Request & response'}{rule.methods.length > 0 && <small className="subcell">{rule.methods.join(', ')}</small>}</td><td><StatusBadge value={rule.action} /></td><td><StatusBadge value={rule.enabled} /></td></tr>)}
          </Table>
        </DataState>
      </Panel>
      <Panel title="Recent DLP blocks" subtitle="Audit events whose reason code is DLP_BLOCKED">
        <DataState loading={activity.isLoading} error={activity.error} empty={!activity.data?.events.length} onRetry={() => void activity.refetch()}>
          <Table headers={['Timestamp', 'Agent', 'Server', 'Method', 'Tool', 'Decision', 'Reason']}>
            {activity.data?.events.map((event, index) => <tr key={`${event.timestamp}-${index}`}><td>{formatDate(event.timestamp)}</td><td>{event.agent_id || '—'}</td><td>{event.server || '—'}</td><td>{event.method || '—'}</td><td>{event.tool || '—'}</td><td><StatusBadge value={event.decision || 'DENY'} /></td><td>{event.reason_code || 'DLP_BLOCKED'}</td></tr>)}
          </Table>
        </DataState>
      </Panel>
    </>
  );
}
