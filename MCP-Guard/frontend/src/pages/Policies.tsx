import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Clock3, History, RotateCcw, Save, Shield, ShieldAlert } from 'lucide-react';
import { api } from '../api/client';
import type { AgentPolicy, PolicySnapshot, ToolRule } from '../api/client';
import { Button, DataState, PageHeader, Panel, StatusBadge, Table, formatDate } from '../components/ui';

interface PolicyRow { agent: string; server: string; kind: string; target: string; action: string; scope: string; enabled: boolean }

function rowsFor(snapshot?: PolicySnapshot): PolicyRow[] {
  if (!snapshot) return [];
  const rows: PolicyRow[] = [];
  for (const [agentId, agentPolicy] of Object.entries(snapshot.policy.agents ?? {})) {
    for (const [serverName, server] of Object.entries((agentPolicy as AgentPolicy).servers ?? {})) {
      const sections: [string, Record<string, ToolRule>][] = [
        ['Tool', server.tools ?? {}], ['Resource', server.resources ?? {}], ['Prompt', server.prompts ?? {}],
      ];
      for (const [kind, items] of sections) for (const [target, rule] of Object.entries(items)) {
        const scope = [...(rule.tenant_ids ?? []).map((item) => `tenant:${item}`), ...(rule.user_ids ?? []).map((item) => `user:${item}`), ...(rule.roles ?? []).map((item) => `role:${item}`)].join(', ');
        rows.push({ agent: agentId, server: serverName, kind, target, action: rule.action, scope: scope || 'All configured identity contexts', enabled: server.enabled !== false });
      }
      for (const [method, action] of Object.entries(server.methods ?? {})) rows.push({ agent: agentId, server: serverName, kind: 'Method', target: method, action, scope: (agentPolicy as AgentPolicy).tenant_ids?.join(', ') || 'All configured identity contexts', enabled: server.enabled !== false });
    }
  }
  return rows;
}

export function Policies() {
  const queryClient = useQueryClient();
  const policy = useQuery({ queryKey: ['policy'], queryFn: api.policy });
  const [editor, setEditor] = useState('');
  const [editorError, setEditorError] = useState('');
  const [success, setSuccess] = useState('');
  const [rollbackVersion, setRollbackVersion] = useState('');
  useEffect(() => { if (policy.data) setEditor(JSON.stringify(policy.data.policy, null, 2)); }, [policy.data]);
  const rows = useMemo(() => rowsFor(policy.data), [policy.data]);
  const save = useMutation({
    mutationFn: (value: unknown) => api.savePolicy(value),
    onSuccess: async (result) => { setSuccess(`Policy version ${result.version} was activated.`); setEditorError(''); await queryClient.invalidateQueries({ queryKey: ['policy'] }); },
    onError: (error) => { setSuccess(''); setEditorError(error instanceof Error ? error.message : 'Policy update failed.'); },
  });
  const rollback = useMutation({
    mutationFn: (version: number) => api.rollbackPolicy(version),
    onSuccess: async (result) => { setSuccess(`Rollback activated as new version ${result.version}.`); setEditorError(''); await queryClient.invalidateQueries({ queryKey: ['policy'] }); },
    onError: (error) => { setSuccess(''); setEditorError(error instanceof Error ? error.message : 'Rollback failed.'); },
  });

  const submitPolicy = () => {
    setEditorError(''); setSuccess('');
    try { save.mutate(JSON.parse(editor)); }
    catch { setEditorError('Policy editor does not contain valid JSON.'); }
  };
  const submitRollback = () => {
    const version = Number(rollbackVersion);
    if (!Number.isInteger(version) || version < 1) { setEditorError('Choose a valid policy history version.'); return; }
    if (!window.confirm(`Restore policy version ${version}? This activates a new version and is checked by the backend.`)) return;
    setSuccess(''); rollback.mutate(version);
  };

  return (
    <>
      <PageHeader eyebrow="ACCESS CONTROL" title="Policies" description="Inspect and publish deny-by-default policy snapshots with version history." action={<span className="version-pill"><span />Active version {policy.data?.version ?? '—'}</span>} />
      <div className="callout callout-info"><Shield size={17} /><span>Policy changes replace the complete runtime snapshot. The backend validates identity assignments, scopes, actions and JSON Schema constraints before activation.</span></div>
      <Panel title="Policy rules" subtitle="A read-only summary of the active policy snapshot">
        <DataState loading={policy.isLoading} error={policy.error} empty={!rows.length} onRetry={() => void policy.refetch()}>
          <Table headers={['Agent', 'Server', 'Scope type', 'Resource / tool', 'Decision', 'Identity scope', 'Status']}>
            {rows.map((row, index) => <tr key={`${row.agent}:${row.server}:${row.kind}:${row.target}:${index}`}><td className="cell-strong">{row.agent}</td><td>{row.server}</td><td><span className="mini-chip">{row.kind}</span></td><td className="cell-strong">{row.target}</td><td><StatusBadge value={row.action} /></td><td className="scope-cell">{row.scope}</td><td><StatusBadge value={row.enabled ? 'enabled' : 'disabled'} /></td></tr>)}
          </Table>
        </DataState>
      </Panel>
      <div className="policy-layout">
        <Panel title="Edit policy snapshot" subtitle="Submit JSON to the backend validator; failed updates remain unsaved" action={<Button onClick={submitPolicy} disabled={save.isPending || policy.isLoading}><Save size={15} />{save.isPending ? 'Publishing…' : 'Validate & publish'}</Button>}>
          <DataState loading={policy.isLoading} error={policy.error} onRetry={() => void policy.refetch()}>
            <textarea className="code-editor" aria-label="Active policy JSON" value={editor} onChange={(event) => { setEditor(event.target.value); setEditorError(''); setSuccess(''); }} spellCheck={false} />
            <p className="editor-hint"><ShieldAlert size={14} /> The backend requires <code>default_action: deny</code> and only accepts agents and servers already configured in the gateway.</p>
          </DataState>
          {editorError && <div className="inline-error" role="alert">{editorError}</div>}{success && <div className="inline-success" role="status"><Check size={15} />{success}</div>}
        </Panel>
        <Panel title="Version history" subtitle="Policy changes live in memory and reset when the gateway restarts">
          <div className="history-list"><DataState loading={policy.isLoading} error={policy.error} empty={!policy.data?.history.length} onRetry={() => void policy.refetch()}>{policy.data?.history.slice().reverse().map((item) => <div className="history-item" key={item.version}><span className="history-icon"><History size={15} /></span><div><strong>Version {item.version} {item.version === policy.data?.version && <span className="current-tag">CURRENT</span>}</strong><small>{item.action} by {item.actor} · {formatDate(item.created_at)}</small></div></div>)}</DataState></div>
          <div className="rollback-form"><label htmlFor="rollback-version">Restore a version</label><div className="field-row"><select id="rollback-version" value={rollbackVersion} onChange={(event) => setRollbackVersion(event.target.value)}><option value="">Choose version…</option>{policy.data?.history.map((item) => <option key={item.version} value={item.version}>{`Version ${item.version} · ${item.action}`}</option>)}</select><Button variant="secondary" onClick={submitRollback} disabled={rollback.isPending || !rollbackVersion}><RotateCcw size={15} />Restore</Button></div><small><Clock3 size={13} />Restoring creates a new active version.</small></div>
        </Panel>
      </div>
    </>
  );
}
