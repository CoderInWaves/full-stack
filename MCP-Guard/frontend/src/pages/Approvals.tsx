import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ClipboardCheck, Copy, ShieldAlert, X } from 'lucide-react';
import { api } from '../api/client';
import type { Approval } from '../api/client';
import { Button, DataState, Modal, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';

const states = ['pending', 'approved', 'rejected', 'expired', 'consumed'];

export function Approvals() {
  const queryClient = useQueryClient();
  const [state, setState] = useState('pending');
  const [selected, setSelected] = useState<Approval | null>(null);
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null);
  const [message, setMessage] = useState('');
  const approvals = useQuery({ queryKey: ['approvals', state], queryFn: () => api.approvals(state), refetchInterval: state === 'pending' ? 15_000 : false });
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'reject' }) => api.decideApproval(id, action),
    onSuccess: async (result) => { setMessage(`Request ${result.approval_id} was ${result.state}.`); setSelected(null); setDecision(null); await queryClient.invalidateQueries({ queryKey: ['approvals'] }); },
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Decision failed.'),
  });
  const confirmDecision = () => { if (selected && decision) decide.mutate({ id: selected.approval_id, action: decision }); };

  return (
    <>
      <PageHeader eyebrow="HUMAN-IN-THE-LOOP" title="Approval center" description="Review and decide on exact tool calls that policy requires an administrator to approve." action={<span className="version-pill"><span />{approvals.data?.approvals.filter((item) => item.state === 'pending').length ?? '—'} pending</span>} />
      <div className="callout callout-warning"><ShieldAlert size={17} /><span>Approval IDs are one-time and bound to the exact original action and identity by the backend. Decisions cannot change the tool arguments.</span></div>
      {message && <div className="inline-success" role="status"><Check size={15} />{message}<button className="message-dismiss" onClick={() => setMessage('')} aria-label="Dismiss message">×</button></div>}
      <Panel title="Approval requests" subtitle="The backend returns request identity and target metadata; arguments and policy reason are not available in this API">
        <div className="filter-row approval-filters"><label htmlFor="approval-state">Request state</label><select id="approval-state" value={state} onChange={(event) => setState(event.target.value)}>{states.map((value) => <option value={value} key={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select><span className="filter-spacer" /><span className="refresh-caption">Refreshes every 15 seconds while viewing pending requests</span></div>
        <DataState loading={approvals.isLoading} error={approvals.error} empty={!approvals.data?.approvals.length} onRetry={() => void approvals.refetch()}>
          {state === 'pending' && !approvals.isLoading && !approvals.error && !approvals.data?.approvals.length ? <div className="empty-panel"><div className="empty-large-icon"><ClipboardCheck size={23} /></div><strong>Nothing needs your attention</strong><p>Approval-required tool calls will appear here when an agent requests them.</p></div> : <Table headers={['Request', 'Agent & tenant', 'Requested action', 'Target server', 'Requested at', 'Expires', 'Status', '']}>
            {approvals.data?.approvals.map((item) => <tr key={item.approval_id}><td><button className="link-button mono" onClick={() => setSelected(item)}>{item.approval_id}</button></td><td><div className="cell-stack"><strong>{item.agent_id}</strong><small>{item.tenant_id || 'No tenant'} · {item.user_id || 'No user'}</small></div></td><td className="cell-strong">{item.tool}</td><td>{item.server}</td><td>{formatDate(item.created_at)}</td><td>{formatDate(item.expires_at)}</td><td><StatusBadge value={item.state} /></td><td>{item.state === 'pending' && <Button className="button-small" onClick={() => { setSelected(item); setDecision(null); }}>Review</Button>}</td></tr>)}
          </Table>}
        </DataState>
      </Panel>
      {selected && <Modal title="Review approval request" description="Confirm the request metadata before making a decision." onClose={() => { setSelected(null); setDecision(null); }}>
        <div className="approval-request-id"><small>EXACT APPROVAL REQUEST ID</small><code>{selected.approval_id}</code><button className="icon-button" aria-label="Copy request ID" onClick={() => void navigator.clipboard?.writeText(selected.approval_id)}><Copy size={14} /></button></div>
        <div className="detail-grid approval-detail"><div><small>Agent</small><strong>{selected.agent_id}</strong></div><div><small>Tenant / user</small><strong>{selected.tenant_id || '—'} / {selected.user_id || '—'}</strong></div><div><small>Tool</small><strong>{selected.tool}</strong></div><div><small>Target server</small><strong>{selected.server}</strong></div><div><small>Requested</small><strong>{formatDate(selected.created_at)}</strong></div><div><small>Expires</small><strong>{formatDate(selected.expires_at)}</strong></div></div>
        <div className="inline-note"><ShieldAlert size={15} />This API does not expose arguments or a policy reason. The backend binds approval to the original request.</div>
        {selected.state === 'pending' && <div className="modal-actions"><Button variant="secondary" onClick={() => setDecision('reject')}><X size={15} />Reject</Button><Button onClick={() => setDecision('approve')}><Check size={15} />Approve</Button></div>}
        {decision && <div className="decision-confirm"><strong>{decision === 'approve' ? 'Approve this exact request?' : 'Reject this request?'}</strong><p>The backend will validate the exact request ID and its current state.</p><div><Button variant="ghost" onClick={() => setDecision(null)}>Cancel</Button><Button variant={decision === 'approve' ? 'primary' : 'danger'} disabled={decide.isPending} onClick={confirmDecision}>{decide.isPending ? 'Submitting…' : `Confirm ${decision}`}</Button></div></div>}
      </Modal>}
    </>
  );
}
