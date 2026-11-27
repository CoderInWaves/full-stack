# Security Design

## Enforcement principles

1. Deny by default. Every protected object or extension method needs an explicit allow.
2. Derive agent, tenant, user, and roles from process configuration or verified transport authentication, never from tool arguments.
3. Recheck authorization when a tool executes even if discovery previously showed it.
4. Recheck original tool policy before releasing a task operation or consuming an approved action.
5. Apply DLP to configured request and response content; do not log secrets or payloads by default.
6. Keep upstream credentials independent from client credentials.

## Identity and authentication

STDIO identity is bound to administrator-controlled process configuration. HTTP accepts SHA-256 hashed high-entropy local bearer tokens and optional signed JWTs. JWT mode checks configured signing algorithms, signature, issuer, audience, expiration, optional not-before, required scopes, configured identity claims, and revoked `jti` values. It fails closed if PyJWT is missing or validation fails. mTLS can be required by configuring gateway TLS, a client CA, and `require_client_certificate`.

The JWT validator is a resource-server component. MCP-Guard does not implement OAuth authorization, OIDC discovery, login, or token issuance. Token hash and `jti` revocation state is in-memory. Agent and admin credentials are separate; only enabled credentials with the `admin` role can call admin routes.

## Authorization

Policy evaluation checks trusted identity and agent state, server assignment, server enablement, explicit rule, tenant/user/role scopes, and JSON Schema constraints. Tools, resource URIs, and prompts are explicitly scoped. Tasks are bound to the identity that initiated the corresponding tool call and are rechecked against current tool policy. Subscriptions and server discovery require explicit method rules. Discovery filtering hides inaccessible objects but never substitutes for execution-time checks.

`server/discover` must be explicitly allowed in a server's `methods` map for clients that use discovery. Valid but unrecognized methods/extensions are denied unless explicitly allowed. Protocol lifecycle and cancellation handling is narrow and does not grant access to arbitrary operations.

Approval requests are bound using an in-process HMAC to the exact tool, arguments, server, agent, tenant, user, and roles. They expire and can be consumed once, and policy is re-evaluated immediately before forwarding. The HMAC key and queue are memory-only. Human approval requires the separate administrator identity.

## Data protection

DLP uses configured regular expressions with input limits and bounded regex matching. Patterns can be scoped by agent, tenant, user, server, method, and direction. Request and response paths cover tool arguments/results, resource text, prompt arguments/results, and task results. Redacted modern MCP tool arguments are mirrored consistently into approved `Mcp-Param-*` headers. DLP is a pattern filter, not semantic or comprehensive classification.

## Transport and secrets

- HTTP binds to loopback by default; configure TLS/mTLS or a trusted TLS terminator before remote exposure.
- `Origin` values, when present, must match an administrator-configured allowlist.
- Client `Authorization`, cookies, `Host`, and hop-by-hop headers are not forwarded to MCP upstreams.
- Upstream authentication is configured separately. REST actions accept only pinned upstream URLs/methods and administrator-owned headers.
- Message sizes and upstream timeouts are bounded. Upstream redirects are disabled.
- STDIO commands are argument arrays and are started without a shell.
- Audit payload logging is disabled by default. Protect config, audit files, and environment secrets using OS permissions and secret management.

## Runtime and admin boundary

Runtime policy snapshots are validated before an atomic reference swap, and admin routes require a distinct admin bearer token. Approval, policy history, task ownership, cache, token rotation, and revocation state do not survive process restart. The service is designed for one process; multiple workers would have independent state.

The admin page itself is a static UI shell; sensitive API data is returned only after admin authorization. The console provides read-only summaries for configured agents, upstream servers, DLP rules, settings, and searchable metadata from the active audit file. Agents, servers, DLP rules, and gateway settings remain startup-configuration managed. Audit responses exclude payloads, errors, and DLP findings and do not include rotated log files.

## Residual risks

MCP-Guard does not detect prompt injection, semantically analyze SQL/code, sandbox upstream servers, secure a direct network path that bypasses it, or protect against compromised administrator configuration. Regex checks can miss encoded/obfuscated data. Policy cannot guarantee the business semantics of an allowed tool. Production deployments need network-level egress controls and least-privilege upstream credentials.
