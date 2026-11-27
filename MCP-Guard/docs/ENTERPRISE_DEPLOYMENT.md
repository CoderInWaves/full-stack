# Enterprise Deployment Notes

MCP-Guard is currently a single-process Python service. Treat each process as one isolated state domain.

## Network placement

- Bind loopback for local use. For remote clients, terminate TLS in MCP-Guard or in a trusted reverse proxy and restrict network ingress.
- If you use a proxy, authenticate and authorize at MCP-Guard as well; an upstream proxy is not a replacement for policy enforcement.
- Restrict agent egress so it cannot reach MCP/REST systems through an unguarded route.
- Use `allowed_origins` for browser clients. Non-browser clients without `Origin` are accepted.
- Do not expose admin endpoints to agent-facing networks. Give operators a separate route/network and separate admin token.

## Credentials and upstream access

- Generate random bearer credentials; store hashes in protected configuration/secret management.
- Use separate agent, administrator, and upstream credentials. Configure only least-privilege upstream credentials.
- For JWT, validate issuer, audience, algorithm, key source, scopes, and identity claims. The gateway validates access tokens but does not issue them.
- Restrict and monitor outbound JWKS access. Configure key/issuer failover outside the gateway.
- Apply mTLS where required and validate certificate renewal and trust-chain procedures.

## Process and state

Run one worker/process for each gateway instance that owns approvals, tasks, policy history, token revocations, and DLP tool-header cache. Do not start multiple Uvicorn workers behind one endpoint: these in-memory records are not shared. Restarting resets runtime policy changes, approvals, tasks, and revocations; store the approved policy snapshot in deployment config.

There is no durable DB or HA replication. Back up YAML, secrets references, audit files, and log-retention configuration using your organization's controls.

## Operations

- Validate config with `mcp-guard validate-config` before deployment.
- Keep `logging.log_arguments` and `logging.log_responses` false unless data owners approve their use.
- Scrape `/metrics` only from a trusted monitoring network with an admin credential.
- Set message limits, timeouts, OS memory/CPU limits, and external rate limits.
- Test policy changes and DLP patterns using synthetic data, then test mTLS/JWKS/network failure behavior in staging.
- Monitor denied actions, authentication failures, upstream failures, DLP events, approval queue age, and audit rotation.

See [Authentication](AUTHENTICATION.md), [Security Design](SECURITY.md), and [Known Limitations](LIMITATIONS.md).
