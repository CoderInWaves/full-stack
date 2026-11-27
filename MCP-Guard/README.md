# MCP-Guard

MCP-Guard is a single-process security gateway for MCP clients and explicitly configured direct REST actions. It binds each request to a trusted identity, applies the same deny-by-default policy engine, checks JSON Schema constraints, inspects configured DLP patterns, and writes payload-free JSONL audit events by default.

It protects the request after an agent tries an action. It does not inspect model reasoning, detect prompt injection, or make a weak upstream service safe.

## Current feature status

| Area | Status |
|---|---|
| STDIO and Streamable HTTP MCP proxy | Implemented and tested |
| Tools, resources, prompts, task ownership, subscriptions, and discovery policies | Implemented and tested for supported request paths |
| Tenant, user, agent, and role policy scopes | Implemented and tested with trusted local/JWT identity contexts |
| Exact-action approval queue and administrator APIs | Implemented and tested; single-process and in-memory |
| Runtime policy snapshots, versions, rollback | Implemented and tested; updates replace a whole snapshot and are in-memory |
| SHA-256 bearer auth, optional signed JWT validation, optional mTLS | Implemented; JWT and live TLS deployment need environment-specific validation |
| Pattern-based DLP and mirrored-header consistency | Implemented and tested; not semantic or comprehensive DLP |
| Prometheus metrics and health endpoints | Implemented and tested |
| Optional OpenTelemetry tracing | Implemented; requires the `telemetry` extra and is not tested against a collector here |
| Python SDK and pinned REST action proxy | Implemented and tested |
| Admin dashboard | React admin console; read-only agent/server/DLP inventory, searchable active-file audit metadata, policy and approval workflows, metrics and settings summary |
| LangChain/LangGraph, OpenAI Agents SDK, CrewAI, Google ADK | Connection examples documented; framework dependencies and live runs are not part of core tests |
| OAuth authorization server, OIDC discovery/login, persistent storage, HA | Not implemented |

The full feature boundaries and residual risks are listed in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Requirements and local installation

Python 3.11 or newer is required. Create and install into a project virtual environment; these commands do not install packages into the global Python environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Optional extras:

```bash
python -m pip install -e '.[auth]'       # PyJWT crypto/JWKS validation
python -m pip install -e '.[telemetry]'  # OpenTelemetry OTLP/HTTP exporter
```

If this checkout already has a `venv/`, use `venv/bin/python -m pip ...` and `venv/bin/mcp-guard ...` in place of activating `.venv`.

## Quick start: STDIO demo

The demo server uses fictional customer records. Validate the configuration and run the request walkthrough:

```bash
.venv/bin/mcp-guard validate-config --config examples/demo_config.yaml
.venv/bin/mcp-guard doctor --config examples/demo_config.yaml
.venv/bin/python examples/run_demo.py
```

The demo allows selected read/report tools and denies `delete_customer`. `update_customer` requires approval; STDIO mode has no HTTP administrator endpoint, so it remains blocked there. The HTTP approval workflow is described in [`docs/APPROVALS.md`](docs/APPROVALS.md).

To connect an MCP desktop client over STDIO, configure it to launch MCP-Guard as the server process:

```json
{
  "mcpServers": {
    "guarded-customers": {
      "command": "/absolute/path/to/MCP-Guard/.venv/bin/mcp-guard",
      "args": ["stdio", "--config", "/absolute/path/to/MCP-Guard/examples/demo_config.yaml"]
    }
  }
}
```

Use absolute paths. MCP-Guard reserves stdout for protocol frames and writes application logs to stderr.

## Quick start: Streamable HTTP

Copy and edit [`examples/http_config.yaml`](examples/http_config.yaml). Generate a random bearer token hash with:

```bash
.venv/bin/mcp-guard hash-token
```

Set the printed hash in `identity.agents[*].api_key_hash` and configure a separate upstream credential under `http.upstream_headers` if needed. Then run:

```bash
.venv/bin/mcp-guard validate-config --config examples/http_config.yaml
.venv/bin/mcp-guard http --config examples/http_config.yaml
```

The default listener is `127.0.0.1:8080`. MCP clients send requests to `POST /mcp`. See [`docs/PROTOCOL_COMPATIBILITY.md`](docs/PROTOCOL_COMPATIBILITY.md) for current and legacy wire requirements.

## Admin APIs and dashboard

The React admin console is served at `GET /admin`. Build and development instructions, the frontend/backend feature matrix, authentication behavior, and current API limitations are documented in [`docs/FRONTEND.md`](docs/FRONTEND.md). Administrator APIs use credentials in `identity.admin_credentials`, separate from agent tokens. The browser holds the entered token in memory only; reload requires signing in again.

The backend supports approvals, whole-policy update/rollback, token/JWT revocation and rotation, metrics, health, and readiness. The console also reads safe summaries for configured agents, upstreams, DLP rules, settings, and payload-free audit events. Agent/server/DLP/settings configuration is startup-managed and cannot be mutated from the UI. The runtime queue, policy history, revocations, and metrics reset on process restart.

For a local UI preview with public demo-only credentials, build the frontend using [`docs/FRONTEND.md`](docs/FRONTEND.md), run `mcp-guard http --config examples/dashboard_demo_config.yaml`, then open `http://127.0.0.1:8080/admin`. The dashboard demo does not require an upstream to be running for its policy and metrics views. Its sample tokens are not safe for network exposure.

## Python SDK and direct REST actions

The MCP SDK talks to `/mcp`, where every call is re-authorized. A direct REST call must use an administrator-pinned action mapping; the caller cannot choose an upstream URL or HTTP method. Each action name uses the same agent/server/tool policy and DLP checks as an MCP tool call.

```python
from mcp_guard import MCPGuard

with MCPGuard("http://127.0.0.1:8080", api_key="agent-bearer-token") as guard:
    tools = guard.list_tools()
    result = guard.call_tool("get_customer", {"customer_id": "C001"})
```

For approval-required calls, catch `MCPGuardApprovalRequired`, let an administrator approve its `approval_id`, then retry the exact arguments with `approval_id=...`. Direct REST configuration and the callable adapter are documented in [`docs/SDK.md`](docs/SDK.md) and [`docs/REST_API.md`](docs/REST_API.md).

## Configuration and policies

All settings live under the `mcp_guard` YAML key. [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) documents fields and trusted identity configuration. Both top-level and policy defaults must remain `deny`; grant explicit permissions only. Add `server/discover: allow` for modern clients that probe server discovery. User and tenant IDs are derived from local credential mappings or validated JWT claims, never from untrusted tool arguments. Use `identity_argument_bindings` when a tool accepts top-level tenant/user/agent fields that must match the verified context; opaque record ownership still needs an upstream check.

## Monitoring

`GET /health` and `GET /health/live` are liveness endpoints. `GET /health/ready` reports configured engine and upstream state. `GET /metrics` requires admin authentication and exposes low-cardinality Prometheus counters and histograms. Set `OTEL_EXPORTER_OTLP_ENDPOINT` and install the `telemetry` extra to send optional traces. Monitoring failures do not grant access.

## Development checks

Run from the project virtual environment:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m mypy src
```

The benchmark command is `python -m tests.benchmark --iterations 1000 --concurrency 1,8,32`. Tests use fake data and in-process upstreams.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [Security design](docs/SECURITY.md) · [Threat model](docs/THREAT_MODEL.md)
- [Installation](docs/INSTALLATION.md) · [Configuration reference](docs/CONFIGURATION.md) · [Known limitations](docs/LIMITATIONS.md)
- [Authentication](docs/AUTHENTICATION.md) · [Policy management](docs/POLICY_MANAGEMENT.md) · [Approvals](docs/APPROVALS.md)
- [Monitoring](docs/MONITORING.md) · [Python SDK](docs/SDK.md) · [REST gateway](docs/REST_API.md)
- [LangChain/LangGraph](docs/integrations/LANGCHAIN.md) · [OpenAI Agents SDK](docs/integrations/OPENAI_AGENTS.md) · [CrewAI](docs/integrations/CREWAI.md) · [Google ADK](docs/integrations/GOOGLE_ADK.md)
- [Enterprise deployment](docs/ENTERPRISE_DEPLOYMENT.md) · [Protocol compatibility](docs/PROTOCOL_COMPATIBILITY.md)
