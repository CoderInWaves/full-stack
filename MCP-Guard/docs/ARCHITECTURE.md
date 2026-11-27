# Architecture

MCP-Guard remains a single-process gateway with raw JSON-RPC handling. It does not convert messages into MCP SDK client/server objects.

```text
MCP client ── STDIO or Streamable HTTP ── MessageRouter ── configured MCP server
     │                                        │
     │                                AccessController
     │                           identity → policy → DLP
     │                                        │
     ├── Python SDK ── MCP / REST action routes┘
     │                            │
     │                            └── fixed administrator-configured REST URL
     │
     └── admin browser ── protected approval/policy/metrics APIs
```

## MCP request path

1. HTTP checks origin/content framing and resolves an identity from a local hashed bearer credential or a validated JWT. STDIO binds identity to `identity.agent_id` in the trusted process configuration.
2. The parser and validator reject invalid UTF-8/JSON-RPC, duplicate keys, unsupported payload shapes, client-sent responses, and oversize messages.
3. `MessageRouter` sends protected operations through the shared controller. `tools/call`, `resources/read`, and `prompts/get` use named rules and scopes. Tasks use an in-memory server-task-to-identity owner record and re-evaluate the original tool policy on every operation. Subscriptions filter requested URIs and emitted events. Unknown methods and optional extensions need an explicit method grant; lifecycle and cancellation messages have narrow handling.
4. Discovery responses are filtered, while each action is still checked when called. Resource URIs and prompt names are checked again when directly requested.
5. DLP scans configured request and response content. Redaction is applied before upstream forwarding; for modern MCP tools with `x-mcp-header` argument annotations, MCP-Guard rebuilds mirrored headers from the redacted body.
6. The gateway forwards only protocol headers and administrator-configured upstream headers. Incoming agent authorization is never copied upstream. JSON responses are bounded and inspected; SSE is filtered event by event.
7. The audit logger records identity, decision, reason, correlation, and latency without payloads by default.

## Direct REST request path

`POST /api/v1/actions/{action}` accepts a JSON object. The action name must have a static entry in `http.rest_actions`; that entry pins the upstream server, URL, method, and administrator-owned headers. The authenticated request is converted into a synthetic tool call and sent through the same tool policy, scope, approval, audit, and DLP logic. Response DLP runs before the response is returned. The endpoint does not proxy arbitrary URLs or caller-selected methods.

The action route is not a transparent gateway for every company API. Any direct path that bypasses MCP-Guard bypasses these controls.

## Identity, policy, and approval state

Local credential mappings and signed JWT claims create the trusted identity context. Request arguments cannot set or change it. Policy snapshots are validated and swapped atomically in process; the bounded version history is volatile. Approval IDs are HMAC-bound to exact action arguments and identity; the approval queue and HMAC key are memory-only and approvals expire and can be consumed only once. Task ownership is also process-local.

There is no database, distributed cache, or supported multi-worker shared state. Run one gateway process per isolated state domain. Multiple workers would have separate approvals, task ownership, policy versions, and revocations.

## Admin console and observability

The `/admin` page is a static browser UI. It provides a minimal approval queue, complete policy snapshot editor/rollback, and metrics view. Its data APIs require a separate admin token. It is not an agent lifecycle, DLP-rule, or searchable audit management console.

`/metrics` exposes bounded-label Prometheus counters/histograms. Optional OpenTelemetry spans cover authentication, request authorization/inspection, upstream forwarding, and response inspection. Exporter setup uses the OTLP HTTP endpoint from standard environment configuration. Tracing never receives request bodies or credentials.

## Protocol boundary

MCP-Guard implements the wire boundary directly. Modern Streamable HTTP validates per-request protocol metadata and mirrored `MCP-Protocol-Version`, `Mcp-Method`, and applicable `Mcp-Name` headers. Legacy Streamable HTTP session headers are opaque pass-through values. It does not translate protocol eras or implement the deprecated HTTP+SSE GET transport.

See [Protocol compatibility](PROTOCOL_COMPATIBILITY.md) for the explicit supported revision and method handling.
