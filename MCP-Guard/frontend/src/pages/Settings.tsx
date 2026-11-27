import { useQuery } from '@tanstack/react-query';
import { FileClock, Globe2, KeyRound, LockKeyhole, Palette, ServerCog, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { DataState, PageHeader, Panel, StatusBadge } from '../components/ui';

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings });
  const value = settings.data;
  return <>
    <PageHeader eyebrow="ADMINISTRATION" title="Settings" description="View the active gateway security posture and supported runtime configuration." />
    <div className="callout callout-info"><LockKeyhole size={17} /><span>Gateway configuration is loaded from YAML and environment variables at startup. These values are read-only in the console; changes require a protected configuration update and restart.</span></div>
    <DataState loading={settings.isLoading} error={settings.error} onRetry={() => void settings.refetch()}>
      {value && <div className="settings-grid">
        <Panel title="General" subtitle="Product and runtime identity"><div className="settings-list"><div><span><ServerCog size={15} />Product name</span><strong>{value.product}</strong></div><div><span><Globe2 size={15} />Environment</span><strong>{value.environment}</strong></div><div><span><ServerCog size={15} />Gateway transport</span><span className="mini-chip">{value.gateway_transport}</span></div><div><span><Globe2 size={15} />HTTP listener</span><strong>{value.listener ? `${value.listener.host}:${value.listener.port}` : 'Not configured'}</strong></div><div><span><Globe2 size={15} />Allowed browser origins</span><strong>{value.allowed_origins.length ? value.allowed_origins.join(', ') : 'None configured'}</strong></div></div></Panel>
        <Panel title="Authentication" subtitle="Sensitive values are never returned"><div className="settings-list"><div><span><KeyRound size={15} />Admin authentication</span><StatusBadge value="Bearer token" /></div><div><span><KeyRound size={15} />OIDC / JWT</span><StatusBadge value={value.jwt_enabled ? 'enabled' : 'not enabled'} /></div><div><span><LockKeyhole size={15} />TLS server certificate</span><StatusBadge value={value.tls_server_certificate_configured} /></div><div><span><LockKeyhole size={15} />mTLS client verification</span><StatusBadge value={value.mtls_required ? 'required' : value.mtls_enabled ? 'optional' : 'not enabled'} /></div></div></Panel>
        <Panel title="Security defaults" subtitle="Request enforcement limits"><div className="settings-list"><div><span>Maximum message size</span><strong>{(value.security.max_message_size / 1024 / 1024).toFixed(1)} MB</strong></div><div><span>Request timeout</span><strong>{value.security.request_timeout_seconds} sec</strong></div><div><span>Approval expiration</span><strong>{value.security.approval_timeout_seconds} sec</strong></div><div><span><ShieldCheck size={15} />DLP engine</span><StatusBadge value={value.security.dlp_enabled} /></div></div></Panel>
        <Panel title="Audit configuration" subtitle="Retention and payload policy as configured"><div className="settings-list"><div><span><FileClock size={15} />Audit file logging</span><StatusBadge value={value.audit.enabled} /></div><div><span>Maximum file size</span><strong>{value.audit.max_size_mb} MB</strong></div><div><span>Rotated file count</span><strong>{value.audit.backup_count}</strong></div><div><span>Payload logging</span><StatusBadge value={value.audit.payload_logging_enabled ? 'enabled' : 'disabled'} /></div><div><span>Retention period</span><strong>{value.audit.retention_days == null ? 'Not configured' : `${value.audit.retention_days} days`}</strong></div></div></Panel>
        <Panel title="Appearance" subtitle="Interface preferences"><div className="appearance-pref"><span className="appearance-icon"><Palette size={18} /></span><div><strong>Color theme</strong><small>Use the moon or sun control in the top navigation to switch the dashboard theme.</small></div><span className="mini-chip">Session only</span></div></Panel>
        <Panel title="Persistence" subtitle="Where settings are stored"><div className="persistence-info"><p>{value.configuration_persistence}</p><small>Administrator mutations to approvals and policies are in-memory. Agents, server configuration, DLP rules, authentication and security settings are startup configuration.</small></div></Panel>
      </div>}
    </DataState>
  </>;
}
