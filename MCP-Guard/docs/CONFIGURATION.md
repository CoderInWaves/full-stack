# Configuration Reference

Configuration is YAML. The file may place all fields under `mcp_guard:` or at its root. `${ENV_VAR}` values are resolved recursively, duplicate YAML keys and unknown fields are rejected.

Validate before starting:

```bash
.venv/bin/mcp-guard validate-config --config examples/http_config.yaml
.venv/bin/mcp-guard doctor --config examples/http_config.yaml
```

## Top-level and STDIO

```yaml
mcp_guard:
  name: MCP-Guard
  environment: development
  transport: http                 # stdio | http
  default_policy: deny
  stdio: { ... }
  http: { ... }
  identity: { ... }
  policy: { ... }
  logging: { ... }
  security: { ... }
  upstreams: { ... }
```

`default_policy` and `policy.default_action` are retained for compatibility and both must be `deny`.

STDIO uses a configured upstream process, started without a shell:

```yaml
transport: stdio
stdio:
  upstream:
    name: customer_database
    command: [python, /absolute/path/to/server.py]
    env: {APP_ENV: production}
identity:
  agent_id: support-agent-01
  agents:
    support:
      id: support-agent-01
      enabled: true
      servers: [customer_database]
```

The STDIO identity is bound to the configuration and is not selected from message contents.

## Streamable HTTP and upstreams

```yaml
transport: http
http:
  host: 127.0.0.1
  port: 8080
  upstream_url: https://mcp.internal.example/mcp
  allowed_origins: []
  upstream_headers:
    Authorization: "Bearer ${MCP_GUARD_UPSTREAM_TOKEN}"
  tls_cert_file: null
  tls_key_file: null
  client_ca_file: null
  require_client_certificate: false
upstreams:
  customer_database:
    name: customer_database
    url: https://mcp.internal.example/mcp
```

- The listener defaults to loopback. `upstream_url` must be HTTP(S), with no embedded credentials or fragment.
- An upstream whose URL matches `upstream_url` supplies the MCP policy server name; otherwise it is `http_upstream`.
- A present `Origin` must exactly match `allowed_origins`. Requests without `Origin` are accepted.
- Client bearer tokens, cookies, `Host`, and hop-by-hop headers are never relayed to the MCP upstream. `http.upstream_headers` are administrator-owned credentials and values.
- TLS fields enable TLS in Uvicorn. A certificate and key are paired. Set `client_ca_file` and `require_client_certificate: true` to require client certificates.
- The transport exposes `POST /mcp`; it does not implement legacy HTTP+SSE `GET` endpoints.

## Agent tokens and trusted identity context

Generate high-entropy bearer credentials and store only their SHA-256 hash in YAML. Use `mcp-guard hash-token` to calculate the digest without echoing the raw token.

```yaml
identity:
  agents:
    support:
      id: support-agent-01
      name: Customer Support
      enabled: true
      servers: [customer_database]
      api_key_hash: "${MCP_GUARD_SUPPORT_TOKEN_HASH}"
      tenant_id: tenant-01
      user_id: service-user
      roles: [customer_support]
      allowed_tenants: [tenant-01]
      allowed_users: []
  credentials:
    support-user-100:
      agent_id: support-agent-01
      api_key_hash: "${MCP_GUARD_USER_100_TOKEN_HASH}"
      enabled: true
      tenant_id: tenant-01
      user_id: user-100
      roles: [customer_support]
```

`identity.credentials` maps separate tokens to trusted per-user/per-tenant contexts for one configured agent. Tenant and user values in request arguments do not change this identity. Agent allowlists (`allowed_tenants`, `allowed_users`) and policy scopes further restrict the context.

## Optional JWT validation

JWT authentication is enabled only when configured. Install `.[auth]` in the project virtual environment. One signing key source is required: HTTPS JWKS URL, a public key map keyed by `kid`, or an HMAC secret.

```yaml
identity:
  jwt:
    enabled: true
    issuer: https://identity.example/issuer
    audience: mcp-guard
    jwks_url: https://identity.example/.well-known/jwks.json
    algorithms: [RS256]
    required_scopes: [mcp:invoke]
    agent_claim: agent_id
    tenant_claim: tenant_id
    user_claim: sub
    roles_claim: roles
    scope_claim: scope
    leeway_seconds: 0
```

JWT signature, explicit algorithm allowlist, issuer, audience, expiry, optional not-before, configured scopes, agent identity, and mapped claims are checked. Unsigned tokens are rejected. `jti` and local token-hash revocations are held in memory until restart. This is a resource-server JWT validator; MCP-Guard does not provide an OAuth authorization server, login flow, OIDC discovery, or client registration. See [Authentication](AUTHENTICATION.md).

## Separate administrator credentials

Admin routes do not accept agent tokens. Configure a separate high-entropy token hash:

```yaml
identity:
  admin_credentials:
    platform-operator:
      id: platform-operator
      api_key_hash: "${MCP_GUARD_ADMIN_TOKEN_HASH}"
      enabled: true
      roles: [admin]
```

Enabled admin credentials must include the `admin` role. The browser dashboard never persists the token; its admin APIs check the bearer credential on every request.

## REST actions

Direct REST access is available only for explicitly pinned actions. The action key is also the policy tool name; its server must be assigned to the calling agent and have a corresponding tool policy.

```yaml
http:
  rest_actions:
    lookup_customer:
      server_name: customer_database
      url: https://customers.internal.example/api/lookup
      method: POST
      upstream_headers:
        Authorization: "Bearer ${CUSTOMER_API_TOKEN}"
```

Clients call `POST /api/v1/actions/lookup_customer` with a JSON object. The target URL and upstream method come only from administrator configuration. `GET` actions accept scalar JSON properties and map them to query parameters. Only `GET`, `POST`, `PUT`, `PATCH`, and `DELETE` are accepted; user-supplied URLs, methods, and headers are not accepted. See [REST API](REST_API.md).

## Policies

Policy hierarchy is agent → server → tool/resource/prompt/method:

```yaml
policy:
  default_action: deny
  agents:
    support-agent-01:
      tenant_ids: [tenant-01]
      roles: [customer_support]
      servers:
        customer_database:
          enabled: true
          tools:
            get_customer:
              action: allow
              tenant_ids: [tenant-01]
              identity_argument_bindings:
                tenant_id: tenant_id
                user_id: user_id
              argument_constraints:
                schema:
                  type: object
                  properties:
                    tenant_id: {type: string}
                    user_id: {type: string}
                    customer_id: {type: string, minLength: 1}
                  required: [tenant_id, user_id, customer_id]
                  additionalProperties: false
            update_customer:
              action: approval_required
          resources:
            "company://tenants/{tenant_id}/customers/{user_id}":
              action: allow
          prompts:
            customer_summary:
              action: allow
          methods:
            server/discover: allow
```

`tenant_ids`, `user_ids`, and `roles` are optional scope filters on agents and named policies. `identity_argument_bindings` maps top-level argument names to trusted `agent_id`, `tenant_id`, or `user_id` values; missing or mismatched fields are denied. Include each bound field in a restrictive JSON Schema. For opaque IDs whose ownership cannot be expressed as an argument field, enforce record-level ownership in the upstream service or use a resource URI template that embeds trusted context.

Resource keys support exact URI matches and `{agent_id}`, `{tenant_id}`, `{user_id}` substitutions. Tools, resources, and prompts are denied without a matching allow rule. Extension methods such as `server/discover`, tasks, and subscriptions require explicit method rules. MCP lifecycle/cancellation notifications have narrow protocol handling. Approval-required tool calls enter the queue only on HTTP mode; STDIO remains fail-closed without an admin endpoint.

Runtime APIs replace a complete `PolicyConfig` snapshot, validate before activation, preserve up to 100 in-memory versions, and support rollback. YAML remains the startup source of truth. See [Policy management](POLICY_MANAGEMENT.md).

## DLP and audit

```yaml
security:
  max_message_size: 1048576
  request_timeout_seconds: 30
  approval_timeout_seconds: 900
  enable_dlp: true
  dlp_patterns:
    - name: internal_id
      pattern: 'ACCT-[0-9]{8}'
      mode: redact
      replacement: '[REDACTED_ACCOUNT]'
      agents: [support-agent-01]
      tenant_ids: [tenant-01]
      user_ids: []
      servers: [customer_database]
      methods: [tools/call]
      directions: [request]
logging:
  format: jsonl
  file: logs/audit.jsonl
  max_size_mb: 100
  backup_count: 5
  log_arguments: false
  log_responses: false
```

Patterns can be scoped by agent, tenant, user, server, method, and direction. Regex input and match time are bounded. Regex DLP is not semantic classification or complete data-loss prevention. Full payload logging is disabled by default because it may persist sensitive values.

## Split policy/identity files

`mcp-guard` accepts `--policy` and `--agents` with HTTP/STDIO commands and config validation. A policy file may wrap its data in `policy:`; an agent file may wrap its data in `agents:`. Use environment variables for secrets.
