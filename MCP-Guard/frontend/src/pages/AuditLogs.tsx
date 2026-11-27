import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, FileClock, Search } from 'lucide-react';
import { api } from '../api/client';
import type { AuditEvent } from '../api/client';
import { Button, DataState, Modal, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';

const PAGE_SIZE = 25;

export function AuditLogs() {
  const [search, setSearch] = useState('');
  const [agent, setAgent] = useState('');
  const [tenant, setTenant] = useState('');
  const [server, setServer] = useState('');
  const [tool, setTool] = useState('');
  const [decision, setDecision] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const params = useMemo(() => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
    if (search.trim()) query.set('q', search.trim());
    if (agent.trim()) query.set('agent_id', agent.trim());
    if (tenant.trim()) query.set('tenant_id', tenant.trim());
    if (server.trim()) query.set('server', server.trim());
    if (tool.trim()) query.set('tool', tool.trim());
    if (decision) query.set('decision', decision);
    if (since) query.set('since', `${since}T00:00:00`);
    if (until) query.set('until', `${until}T23:59:59.999999`);
    return query;
  }, [agent, decision, page, search, server, since, tenant, tool, until]);
  const audit = useQuery({ queryKey: ['audit', params.toString()], queryFn: () => api.audit(params) });
  const exportCsv = () => {
    const rows = audit.data?.events ?? [];
    if (!rows.length) return;
    const columns: (keyof AuditEvent)[] = ['timestamp', 'agent_id', 'tenant_id', 'user_id', 'server', 'method', 'tool', 'decision', 'reason_code', 'request_id'];
    const csv = [columns.join(','), ...rows.map((row) => columns.map((column) => `"${String(row[column] ?? '').replaceAll('"', '""')}"`).join(','))].join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'mcp-guard-audit-current-page.csv'; anchor.click(); URL.revokeObjectURL(url);
  };

  return (
    <>
      <PageHeader eyebrow="COMPLIANCE & FORENSICS" title="Audit logs" description="Search the active JSONL audit file. Only structured metadata is returned; payloads and errors are omitted." action={<Button variant="secondary" onClick={exportCsv} disabled={!audit.data?.events.length}><Download size={15} />Export this page</Button>} />
      {audit.data?.truncated && <div className="callout callout-warning"><FileClock size={17} /><span>The active audit file exceeds the bounded read window; older records may not appear. Rotated audit files are not included.</span></div>}
      <Panel title="Filter events" subtitle="Filters are applied by the authenticated audit endpoint">
        <div className="audit-filters">
          <label className="search-field"><span>Search</span><div><Search size={15} /><input value={search} placeholder="Agent, method, request ID…" onChange={(event) => { setSearch(event.target.value); setPage(0); }} /></div></label>
          <label><span>Agent</span><input value={agent} onChange={(event) => { setAgent(event.target.value); setPage(0); }} placeholder="Any agent" /></label>
          <label><span>Tenant</span><input value={tenant} onChange={(event) => { setTenant(event.target.value); setPage(0); }} placeholder="Any tenant" /></label>
          <label><span>Server</span><input value={server} onChange={(event) => { setServer(event.target.value); setPage(0); }} placeholder="Any server" /></label>
          <label><span>Tool</span><input value={tool} onChange={(event) => { setTool(event.target.value); setPage(0); }} placeholder="Any tool" /></label>
          <label><span>Decision</span><select value={decision} onChange={(event) => { setDecision(event.target.value); setPage(0); }}><option value="">All decisions</option>{['ALLOW', 'DENY', 'APPROVAL_REQUIRED', 'REDACT', 'APPROVE', 'REJECT'].map((value) => <option key={value}>{value}</option>)}</select></label>
          <label><span>From</span><input type="date" value={since} onChange={(event) => { setSince(event.target.value); setPage(0); }} /></label>
          <label><span>To</span><input type="date" value={until} onChange={(event) => { setUntil(event.target.value); setPage(0); }} /></label>
        </div>
      </Panel>
      <Panel title="Event records" subtitle={audit.data ? `${audit.data.total} matching event${audit.data.total === 1 ? '' : 's'} in the available file window` : 'Matching audit records'}>
        <DataState loading={audit.isLoading} error={audit.error} onRetry={() => void audit.refetch()}>
          {audit.data && audit.data.events.length === 0 ? <div className="empty-panel"><div className="empty-large-icon"><FileClock size={22} /></div><strong>No audit events match</strong><p>Try changing your filters or generate a gateway request.</p></div> : <Table headers={['Timestamp', 'Agent', 'Tenant', 'User', 'Server', 'Method / tool', 'Decision', 'Reason', 'Request ID', '']}>
            {audit.data?.events.map((event, index) => <tr key={`${event.timestamp}-${event.request_id ?? index}`}><td>{formatDate(event.timestamp)}</td><td>{event.agent_id || '—'}</td><td>{event.tenant_id || '—'}</td><td>{event.user_id || '—'}</td><td>{event.server || '—'}</td><td><div className="cell-stack"><strong>{event.tool || '—'}</strong><small>{event.method || '—'}</small></div></td><td><StatusBadge value={event.decision || 'unknown'} /></td><td className="mono">{event.reason_code || '—'}</td><td className="mono">{event.request_id || event.correlation_id || '—'}</td><td><Button variant="ghost" className="button-small" onClick={() => setSelected(event)}>Details</Button></td></tr>)}
          </Table>}
        </DataState>
        <div className="pagination"><span>Page {page + 1} of {Math.max(1, Math.ceil((audit.data?.total ?? 0) / PAGE_SIZE))} <small>· {audit.data?.source ?? 'active file'}</small></span><div><Button variant="secondary" className="button-small" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</Button><Button variant="secondary" className="button-small" disabled={!audit.data?.has_more} onClick={() => setPage((value) => value + 1)}>Next</Button></div></div>
      </Panel>
      {selected && <Modal title="Audit event" description="Structured, payload-free event details." onClose={() => setSelected(null)}><div className="detail-grid audit-detail">{Object.entries(selected).filter(([key]) => key !== 'arguments' && key !== 'response').map(([key, value]) => <div key={key}><small>{key.replaceAll('_', ' ')}</small><strong className={key === 'request_id' || key === 'correlation_id' ? 'mono' : ''}>{typeof value === 'number' ? `${value} ms` : String(value ?? '—')}</strong></div>)}</div><div className="inline-note"><FileClock size={15} />Secrets, request payloads, response bodies and error text are not included by the backend endpoint.</div></Modal>}
    </>
  );
}
