import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from 'react';
import { AlertCircle, Check, LoaderCircle, RefreshCw } from 'lucide-react';

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}

export function Panel({ title, subtitle, action, children, className = '' }: PropsWithChildren<{ title: string; subtitle?: string; action?: ReactNode; className?: string }>) {
  return <section className={`panel ${className}`}><div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>;
}

export function MetricCard({ label, value, detail, icon, tone = 'blue' }: { label: string; value: string | number; detail: string; icon: ReactNode; tone?: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon tone-${tone}`}>{icon}</span></div><strong className="metric-value">{value}</strong><small>{detail}</small></article>;
}

export function StatusBadge({ value }: { value: string | boolean | null | undefined }) {
  const text = typeof value === 'boolean' ? (value ? 'Enabled' : 'Disabled') : value ?? 'Unknown';
  const normalized = String(text).toLowerCase().replaceAll('_', ' ');
  let tone = 'neutral';
  if (['healthy', 'allowed', 'active', 'enabled', 'available', 'approved', 'ready'].includes(normalized)) tone = 'success';
  else if (['denied', 'blocked', 'unavailable', 'critical', 'rejected', 'expired', 'not ready'].includes(normalized)) tone = 'danger';
  else if (['pending', 'approval required', 'warning'].includes(normalized)) tone = 'warning';
  return <span className={`status-badge badge-${tone}`}><i />{text}</span>;
}

export function DataState({ loading, error, empty, onRetry, children }: PropsWithChildren<{ loading?: boolean; error?: Error | null; empty?: boolean; onRetry?: () => void }>) {
  if (loading) return <div className="data-state"><LoaderCircle className="spin" size={21} /><span>Loading data…</span></div>;
  if (error) return <div className="data-state state-error"><AlertCircle size={20} /><span>{error.message}</span>{onRetry && <Button variant="secondary" className="button-small" onClick={onRetry}><RefreshCw size={14} />Retry</Button>}</div>;
  if (empty) return <div className="data-state"><span>No records are available yet.</span></div>;
  return <>{children}</>;
}

export function EmptyNotice({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return <div className="empty-notice"><span className="empty-check"><Check size={18} /></span><div><strong>{title}</strong><p>{body}</p></div>{action}</div>;
}

export function Table({ headers, children, className = '' }: PropsWithChildren<{ headers: string[]; className?: string }>) {
  return <div className={`table-wrap ${className}`}><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}

export function Button({ children, variant = 'primary', className = '', ...props }: PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }>) {
  return <button className={`button button-${variant} ${className}`} {...props}>{children}</button>;
}

export function Modal({ title, description, children, onClose }: PropsWithChildren<{ title: string; description?: string; onClose: () => void }>) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><button className="icon-button modal-close" onClick={onClose} aria-label="Close dialog">×</button><h2 id="modal-title">{title}</h2>{description && <p>{description}</p>}{children}</section></div>;
}

export function formatDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}
