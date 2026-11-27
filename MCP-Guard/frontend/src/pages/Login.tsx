import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { ArrowRight, LockKeyhole, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api, setAdminToken } from '../api/client';
import { useAuth } from '../App';
import { Button } from '../components/ui';

const tokenSchema = z.object({ token: z.string().trim().min(1, 'Enter your administrator token.') });
type LoginValues = z.infer<typeof tokenSchema>;

export function Login() {
  const [apiError, setApiError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<LoginValues>({ defaultValues: { token: '' } });

  const onSubmit = handleSubmit(async (values) => {
    setApiError('');
    const validated = tokenSchema.safeParse(values);
    if (!validated.success) {
      setError('token', { message: validated.error.issues[0]?.message });
      return;
    }
    const token = validated.data.token;
    setAdminToken(token);
    try {
      const session = await api.session();
      login(session, token);
      navigate('/', { replace: true });
    } catch (error) {
      setAdminToken('');
      setApiError(error instanceof Error ? error.message : 'Administrator authentication failed.');
    }
  });

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="login-brand"><span className="brand-mark"><Shield size={20} /></span><span><strong>MCP-Guard</strong><small>SECURITY CONSOLE</small></span></div>
        <div className="login-intro"><div className="eyebrow">ADMINISTRATOR ACCESS</div><h1>Welcome back</h1><p>Sign in with an administrator credential to manage your MCP gateway.</p></div>
        <form onSubmit={onSubmit} className="login-form">
          <label htmlFor="admin-token">Administrator token</label>
          <input id="admin-token" type="password" autoComplete="current-password" spellCheck={false} placeholder="Enter your admin bearer token" {...register('token')} aria-invalid={Boolean(errors.token)} />
          {errors.token && <small className="field-error">{errors.token.message}</small>}
          {apiError && <div className="inline-error" role="alert"><LockKeyhole size={15} />{apiError}</div>}
          <Button type="submit" disabled={isSubmitting} className="login-submit">{isSubmitting ? 'Checking access…' : 'Continue'}<ArrowRight size={16} /></Button>
        </form>
        <div className="login-security"><LockKeyhole size={15} /><span>Your token stays in page memory and is cleared when you sign out or reload.</span></div>
      </section>
      <aside className="login-aside"><div className="login-orbit orbit-one" /><div className="login-orbit orbit-two" /><div className="login-aside-content"><span className="aside-eyebrow"><i /> GATEWAY PROTECTION</span><h2>Secure every agent.<br />Govern every action.</h2><p>One control plane for identity-aware authorization, human approvals and data protection across MCP tools.</p><div className="login-feature"><span><Shield size={17} /></span><div><strong>Policy enforced at the gateway</strong><small>Each request is checked by MCP-Guard before it reaches an upstream server.</small></div></div><div className="login-feature"><span><LockKeyhole size={17} /></span><div><strong>Administrative actions are authenticated</strong><small>Backend authorization remains the source of truth for every change.</small></div></div></div><div className="login-aside-footer">MCP-GUARD · AI AGENT SECURITY</div></aside>
    </main>
  );
}
