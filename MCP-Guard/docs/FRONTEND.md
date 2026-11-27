# MCP-Guard admin frontend

The admin console is a React, TypeScript and Vite application under `frontend/`. The production build is emitted into `src/mcp_guard/static/` and served by the existing Starlette HTTP gateway at `/admin`. Browser routes use the URL hash so the Python gateway does not need an SPA fallback route.

## Local development

Use Node.js/npm for the frontend and the project virtual environment for the Python gateway. No global Python packages are installed or modified.

Terminal 1:

```bash
cd frontend
npm install
npm run dev
```

Terminal 2, from the repository root:

```bash
venv/bin/mcp-guard http --config examples/dashboard_demo_config.yaml
```

Open `http://127.0.0.1:5173/#/login` and use the local demo administrator token `local-demo-admin-token`. The Vite development server proxies `/admin`, `/health`, and `/metrics` to `127.0.0.1:8080`. This public demo configuration is loopback-only and must not be exposed to a network.

## Build and serve through MCP-Guard

```bash
cd frontend
npm install
npm run build
cd ..
venv/bin/mcp-guard http --config examples/dashboard_demo_config.yaml
```

Open `http://127.0.0.1:8080/admin`. Vite writes production assets to `src/mcp_guard/static/`; those assets are included in the Python package. Rebuild after frontend source changes.

Frontend checks:

```bash
cd frontend
npm test
npm run build
```

## API integration matrix

| Frontend module | Backend endpoint(s) | Status / constraint |
|---|---|---|
| Overview | `/metrics`, `/health/ready`, `/admin/approvals`, `/admin/agents`, `/admin/servers`, `/admin/audit` | Live aggregate counters and readiness; request records are bounded to recent audit entries. |
| Agents | `/admin/agents`, `/admin/policy`, `/admin/audit` | Read-only configured identities, permissions and recent events. Registration, edit, enable/disable and server assignment APIs do not exist. |
| MCP servers | `/admin/servers`, `/health/ready` | Read-only safe endpoint summaries; credentials and command arguments are omitted. Runtime server editing and connectivity-test APIs do not exist. |
| Policies | `/admin/policy` GET/PUT; `/admin/policy/rollback/{version}` POST | Full snapshot view/editor, backend validation, version history and rollback. In-memory; requires configured agent/server identities. |
| Approvals | `/admin/approvals`; `/admin/approvals/{id}/decision` POST | List and exact-ID approve/reject. API returns no request arguments or policy explanation. Queue is in-memory. |
| Audit logs | `/admin/audit` | Bounded metadata-only search, filters, pagination and current-page CSV. Reads the active JSONL file only; rotated files are not included. |
| DLP | `/admin/dlp`, `/admin/audit` | Read-only configured rules and matching block events. Runtime rule edit/test APIs do not exist. |
| Monitoring | `/metrics`, `/health/ready`, `/admin/approvals` | Actual counters and component status. No time series, request-rate gauge or per-agent/tool metric labels are provided. |
| Integrations | Repository integration guides and SDK docs | Examples are linked to their source docs. These are setup guides, not framework-specific plugins. |
| Settings | `/admin/settings` | Safe runtime configuration summary. Gateway settings persist in startup YAML/environment, not through console mutations. |
| Authentication | `/admin/session` and admin bearer auth on all `/admin/*` data APIs | Token stays in browser memory; no login cookie/session endpoint is present. Reload requires signing in again. |

The admin page is a public static shell, but every data API checks the distinct administrator bearer credential on the backend. Client route protection is only a usability layer; backend authorization remains authoritative.
