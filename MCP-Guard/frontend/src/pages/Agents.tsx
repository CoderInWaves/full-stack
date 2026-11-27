import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot, Eye, KeyRound, Plus, ShieldAlert } from 'lucide-react';
import { api } from '../api/client';
import type { Agent } from '../api/client';
import { Button, DataState, EmptyNotice, Modal, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';

export function Agents() {
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.agents });
  const [selected, setSelected] = useState<Agent | null>(null);
  const policy = useQuery({ queryKey: ['policy'], queryFn: api.policy, enabled: Boolean(selected) });
  const auditParams = new URLSearchParams({ limit: '20', offset: '0', ...(selected ? { agent_id: selected.id } : {}) });
  const recent = useQuery({ queryKey: ['audit', 'agent', selected?.id], queryFn: () => api.audit(auditParams), enabled: Boolean(selected) });
  const policySummary = selected ? Object.entries(policy.data?.policy.agents[selected.id]?.servers ?? {}) : [];

  return (
    <>
      <PageHeader eyebrow="IDENTITY & ACCESS" title="Agents" description="Review configured agent identities, tenant context and server assignments." action={<Button disabled title="Agent registration is managed by startup configuration in this backend."><Plus size={16} /> Register agent</Button>} />
      <EmptyNotice title="Agent configuration is read-only here" body="MCP-Guard loads agent identities and credentials at startup. Registration, enable/disable, token rotation UI and server assignments are not available as runtime agent APIs." />
      <Panel title="Configured agents" subtitle={`${agents.data?.agents.length ?? '—'} identities from gateway configuration`}>
        <DataState loading={agents.isLoading} error={agents.error} empty={!agents.data?.agents.length} onRetry={() => void agents.refetch()}>
          <Table headers={['Agent', 'Tenant', 'Authentication', 'Assigned servers', 'Status', 'Last activity', '']}>
            {agents.data?.agents.map((agent) => <tr key={agent.id}>
              <td><div className="primary-cell"><span className="table-avatar"><Bot size={15} /></span><span><strong>{agent.name}</strong><small>{agent.id}</small></span></div></td>
              <td>{agent.tenant_ids.length ? agent.tenant_ids.join(', ') : <span className="muted">No tenant scope</span>}</td>
              <td><span className="inline-status"><KeyRound size={14} /><StatusBadge value={agent.authentication_configured ? 'configured' : 'unknown'} /></span></td>
              <td>{agent.servers.length ? agent.servers.map((server) => <span className="mini-chip" key={server}>{server}</span>) : '—'}</td>
              <td><StatusBadge value={agent.enabled ? 'active' : 'disabled'} /></td>
              <td>{agent.last_activity ? formatDate(agent.last_activity) : <span className="muted">Not tracked</span>}</td>
              <td><Button variant="ghost" className="button-small" onClick={() => setSelected(agent)}><Eye size={15} /> View</Button></td>
            </tr>)}
          </Table>
        </DataState>
      </Panel>

      {selected && <Modal title={selected.name} description={`Agent identity · ${selected.id}`} onClose={() => setSelected(null)}>
        <div className="detail-grid"><div><small>Authentication</small><StatusBadge value={selected.authentication_configured ? 'configured' : 'unknown'} /></div><div><small>Enabled</small><StatusBadge value={selected.enabled} /></div><div><small>Tenant scope</small><strong>{selected.tenant_ids.join(', ') || 'Not configured'}</strong></div><div><small>Roles</small><strong>{selected.roles.join(', ') || 'Not configured'}</strong></div><div className="detail-span"><small>Assigned MCP servers</small><strong>{selected.servers.join(', ') || 'None configured'}</strong></div></div>
        <div className="detail-section"><h3>Policy permissions</h3>{policy.isLoading ? <p>Loading policy…</p> : policySummary.length ? policySummary.map(([server, rules]) => <div key={server} className="permission-row"><strong>{server}</strong><span>{Object.keys(rules.tools ?? {}).length} tools · {Object.keys(rules.resources ?? {}).length} resources · {Object.keys(rules.prompts ?? {}).length} prompts</span></div>) : <p>No server permissions are present in the active policy snapshot.</p>}</div>
        <div className="detail-section"><h3>Recent request history</h3><DataState loading={recent.isLoading} error={recent.error} empty={!recent.data?.events.length} onRetry={() => void recent.refetch()}>{recent.data?.events.slice(0, 5).map((event, index) => <div key={`${event.timestamp}-${index}`} className="permission-row"><span>{event.tool || event.method || 'Request'} · {event.server || 'unknown server'}</span><span><StatusBadge value={event.decision || 'unknown'} /> {formatDate(event.timestamp)}</span></div>)}</DataState></div>
        <div className="inline-note"><ShieldAlert size={15} /> Credential hashes and raw API tokens are never returned by this page.</div>
      </Modal>}
    </>
  );
}
