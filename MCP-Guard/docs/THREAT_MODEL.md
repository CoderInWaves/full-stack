# MCP-Guard Threat Model

## Assets

- Upstream MCP servers and pinned REST APIs.
- Customer/business data returned by tools, resources, and prompts.
- Integrity of state-changing actions and approval decisions.
- Identity credentials, upstream credentials, policy files, and audit events.

## Trust boundaries and actors

| Actor | Capability | Assumed boundary |
|---|---|---|
| Agent/client | Sends arbitrary protocol requests and arguments using its credential | Not trusted to self-assert identity or permissions |
| End user | Influences agent input and may cause unwanted calls | Does not directly receive admin credentials |
| MCP/REST upstream | Executes configured operations and returns data | Must be administrator-selected and separately least-privileged |
| Gateway administrator | Configures upstreams, credentials, identity and policies | Trusted; configuration access is a root-level capability |
| Attacker with network reach | Sends traffic to exposed listener or attempts browser-origin access | Must be constrained with TLS, network policy, auth, and Origin allowlists |
| Compromised gateway host | Reads process memory, config, credentials, and audit files | Out of scope for in-process controls |

## Threats, controls, residual risk

### Forged agent, tenant, or user context

**Threat:** A caller adds another agent/user/tenant to arguments or guesses another user's resource URI.

**Controls:** HTTP context comes from a credential mapping or verified JWT. STDIO context comes from configured identity. Policy scopes, allowed tenant/user lists, URI-template substitution, and task ownership are evaluated using that trusted context. Direct REST arguments cannot select the target URL or replace identity context.

**Residual risk:** Stolen bearer credentials, overbroad upstream permissions, or compromised identity-provider signing keys can still authorize unwanted actions.

### Unauthorized or destructive operations

**Threat:** Prompt injection or a malicious caller triggers a forbidden tool, resource, prompt, task, subscription, or extension.

**Controls:** Explicit default-deny policy, named-rule checks, JSON Schema validation, filtered discovery, task ownership, and explicit method grants. Approval-required actions are HMAC-bound, one-time, expire, and recheck current policy before forwarding.

**Residual risk:** An allowed tool may have unsafe semantics. Approval and policy state is in-memory, so multi-process deployment is unsupported.

### Data exfiltration or secret disclosure

**Threat:** Sensitive request fields or upstream responses cross a boundary or are copied into logs.

**Controls:** Configurable request/response DLP; request redaction before forwarding; redacted MCP header mirrors; separate upstream credentials; audit payload logging disabled by default.

**Residual risk:** Regex patterns can miss encoded, fragmented, obfuscated, or semantic content. Opt-in payload logging can capture sensitive information.

### Replay or mutation after approval

**Threat:** A caller reuses a human approval with modified args, identity, server, or action.

**Controls:** Approval fingerprint covers action, canonical arguments, agent, tenant, user, roles, server, and expiry; records can be consumed once; modified calls fail closed.

**Residual risk:** Gateway restart discards pending approval records. A compromised administrator account can approve an action.

### Resource exhaustion and malformed traffic

**Threat:** Oversized frames, malformed JSON, pathological patterns, upstream stalls, or connection floods consume resources.

**Controls:** Strict parsing, body limits, regex bounds/timeouts, upstream timeouts, bounded in-memory queues, bounded policy history, disabled redirects, and upstream response limits.

**Residual risk:** There is no distributed rate limiter or overload queue. Operators must set network and process resource limits.

### Credential exposure or bypass

**Threat:** Client auth leaks upstream or an agent calls upstream directly.

**Controls:** MCP client auth is not implicitly forwarded. Upstream credentials are configured separately. REST actions use pinned targets and methods. Bind to loopback by default.

**Residual risk:** Network access to a direct upstream route bypasses MCP-Guard entirely. Enforce egress restrictions outside this process.

## Security boundaries

MCP-Guard does not detect prompt injection, sandbox upstream processes, understand model reasoning, or defend a compromised gateway host/admin. OIDC/OAuth issuance, persistent distributed state, HA, and complete DLP are outside the current implementation. Review [Security Design](SECURITY.md) and [Known Limitations](LIMITATIONS.md) before production deployment.
