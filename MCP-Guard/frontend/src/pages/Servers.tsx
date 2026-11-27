import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Eye, Network, Plus, Server, ShieldCheck, Wifi } from 'lucide-react';
import { api } from '../api/client';
import type { McpServer } from '../api/client';
import { Button, DataState, EmptyNotice, Modal, PageHeader, Panel, StatusBadge, Table } from '../components/ui';

export function Servers() {
  const servers = useQuery({ queryKey: ['servers'], queryFn: api.servers });
  const agents = useQuery({ queryKey: ['agents'], queryFn: api.agents });
  const [selected, setSelected] = useState<McpServer | null>(null);
  const assignedNames = new Map((agents.data?.agents ?? []).map((agent) => [agent.id, agent.name]));

  return (
    <>
      <PageHeader eyebrow="UPSTREAM INVENTORY" title="MCP servers" description="Inspect upstreams configured for the gateway and the agents assigned to them." action={<Button disabled title="Upstream registration and runtime configuration updates are not supported."><Plus size={16} /> Add server</Button>} />
      <EmptyNotice title="Server configuration is read-only" body="MCP-Guard reads upstream endpoints and STDIO commands from startup configuration. Changes require a config edit and gateway restart; credentials and environment values are omitted here." />
      <Panel title="Configured upstreams" subtitle="Connection state is shown only when the gateway can observe it">
        <DataState loading={servers.isLoading} error={servers.error} empty={!servers.data?.servers.length} onRetry={() => void servers.refetch()}>
          <Table headers={['Server', 'Transport', 'Configured endpoint', 'Assigned agents', 'Connection', '']}>
            {servers.data?.servers.map((server) => <tr key={server.name}>
              <td><div className="primary-cell"><span className="table-avatar"><Network size={15} /></span><span><strong>{server.name}</strong><small>Configured upstream</small></span></div></td>
              <td><span className="mini-chip">{server.transport.toUpperCase()}</span></td>
              <td className="endpoint-cell">{server.endpoint}</td>
              <td>{server.assigned_agents.length ? server.assigned_agents.map((id) => <span className="mini-chip" key={id}>{assignedNames.get(id) ?? id}</span>) : <span className="muted">No assignment found</span>}</td>
              <td><StatusBadge value={server.status} /></td>
              <td><Button variant="ghost" className="button-small" onClick={() => setSelected(server)}><Eye size={15} /> Details</Button></td>
            </tr>)}
          </Table>
        </DataState>
      </Panel>
      <div className="note-grid"><div className="note-card"><Wifi size={18} /><div><strong>Connectivity checks</strong><p>The HTTP transport reports configured upstream reachability after a proxied request. A separate safe test-connectivity API is not available.</p></div></div><div className="note-card"><ShieldCheck size={18} /><div><strong>Credentials stay private</strong><p>Upstream authorization headers, environment variables and URL query parameters are excluded from these summaries.</p></div></div></div>
      {selected && <Modal title={selected.name} description="Upstream configuration summary" onClose={() => setSelected(null)}><div className="detail-grid"><div><small>Transport</small><strong>{selected.transport.toUpperCase()}</strong></div><div><small>Observed health</small><StatusBadge value={selected.status} /></div><div className="detail-span"><small>Endpoint / command</small><strong className="mono">{selected.endpoint}</strong></div><div className="detail-span"><small>Assigned agents</small><strong>{selected.assigned_agents.map((id) => assignedNames.get(id) ?? id).join(', ') || 'No assignments listed'}</strong></div></div><p className="muted modal-footnote"><Server size={14} /> No upstream credentials or process arguments are displayed.</p></Modal>}
    </>
  );
}
