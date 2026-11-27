# Known Limitations and Feature Status

This page distinguishes working code from areas that still need deployment-specific or broader product work.

## Implemented and tested

- STDIO proxy and modern/legacy Streamable HTTP request handling.
- Per-operation tool, resource, prompt, task ownership, subscription, and discovery enforcement with default deny.
- Trusted tenant/user/role identity contexts from configured credentials; optional JWT claim mapping is code-implemented but needs the auth extra.
- HMAC-bound approvals, separate administrator APIs, runtime policy snapshots, metrics, health, Python SDK, fixed REST action gateway, and basic approval/policy dashboard.
- Regex DLP request/response inspection and consistency for HTTP mirrored tool headers.

The local automated suite covers the security behavior described above. It does not demonstrate every third-party client or production topology.

## Partial or deployment-dependent

### Authentication

SHA-256 bearer mapping is available. Signed JWT validation is optional and requires `.[auth]`; this project environment did not include PyJWT, so live signature/JWKS verification was not exercised here. HTTPS JWKS retrieval, key rollover, issuer outage behavior, and certificate trust must be validated against the deployment identity provider. mTLS server configuration exists but was not exercised with live client certificates.

There is no OAuth authorization server, OIDC discovery/login, client registration, or interactive user consent flow. Local token-hash/JWT revocation, rotation state, and their mappings are process-memory state and reset at restart.

### Runtime policy and approvals

Runtime updates replace a complete policy snapshot, not individual policy entities. The version journal is bounded to 100 snapshots and held in memory. YAML remains the restart source of truth.

Approvals are single-process and in memory. The request details are redacted by default; there is no durable repository or built-in notification delivery. Admin approval APIs exist, and the small UI can approve or reject. STDIO has no HTTP admin endpoint, so approval-required STDIO calls remain blocked.

### Dashboard and administration

The dashboard is a basic approval/policy/metrics console. It does not manage agent records, credentials, DLP rules, searchable audit logs, or user roles. Create and rotate configured credentials through protected deployment processes.

### Direct REST paths

The gateway protects only explicitly configured action keys at `/api/v1/actions/{action}`. It does not automatically intercept other Python functions or arbitrary REST traffic. Use the SDK wrapper or native MCP client to route through MCP-Guard; remove agents' direct network access to protected systems where enforcement is required.

### Framework integrations

LangChain/LangGraph, OpenAI Agents SDK, CrewAI, and Google ADK examples use their documented MCP clients and connect to `/mcp`. They are documentation/examples, not runtime dependencies or tested end-to-end framework builds. Framework releases can change their configuration APIs; verify against the linked official references.

### OpenTelemetry

Tracing is optional and uses the OTLP HTTP exporter when `.[telemetry]` is installed and `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The full test environment did not include the telemetry extra or a collector. Prometheus metrics are built in and do not require an exporter package.

## Security limitations

### Regex DLP is not complete data classification

The DLP engine applies configured bounded regex patterns to selected structured request/response text. It is not semantic classification and does not reliably identify encoded, fragmented, obfuscated, multilingual, or novel secrets. A replacement can change application data. Test patterns against real schemas using non-production data.

### Opaque record ownership

Tenant/user scopes restrict who can invoke a policy rule. Configure `identity_argument_bindings` when a tool takes top-level tenant/user/agent fields and must match them to the verified identity. MCP-Guard cannot infer ownership for opaque record IDs by itself; the upstream must enforce object-level ownership or the tool must accept identity-bound fields.

### DLP rule versioning

DLP patterns are loaded from YAML at startup. They do not have independent runtime create/update/version/rollback APIs; the runtime policy API only changes authorization policy snapshots.

MCP-Guard does not detect prompt injection, analyze model reasoning, parse SQL semantics, sandbox upstream servers, or protect credentials that agents can use to connect directly to an upstream.

### Process boundaries

The gateway is a single process with in-memory approval, task ownership, policy history, revocation, and tool-header cache state. Multiple workers do not share these. There is no HA failover or database-backed state.

## Protocol and operational limitations

- JSON-RPC batches are rejected.
- STDIO serves one configured client/upstream process and does not multiplex clients.
- The old HTTP+SSE `2024-11-05` transport is unsupported; no translation between legacy handshake-era and current protocol revisions is performed.
- SSE responses are inspected incrementally; downstream clients must support the negotiated Streamable HTTP response behavior.
- REST action GET routes accept only scalar JSON values. Arbitrary path/query transformation is not configured.
- Audit rotation occurs on writes, not on a schedule. Backups and durable policy/configuration recovery are operator responsibilities.
- HTTP binds to loopback by default. Exposing it externally requires TLS, strong identity controls, network policy, and careful review of admin access.

See [Threat model](THREAT_MODEL.md) and [Enterprise deployment](ENTERPRISE_DEPLOYMENT.md) before placing the gateway in a production path.
