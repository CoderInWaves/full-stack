# Authentication and Identity

MCP-Guard distinguishes request authentication from administrator-controlled identity. No authentication mode trusts `agent_id`, `tenant_id`, `user_id`, or roles supplied inside a tool argument.

## Local bearer credentials

Generate a high-entropy token outside source control, then run `mcp-guard hash-token` to store only its SHA-256 digest in config. At runtime the HTTP client sends `Authorization: Bearer <token>`. The raw caller token is not forwarded upstream.

`identity.credentials` supports separate tokens that map to one agent with fixed tenant/user/role values. Agent-level `allowed_tenants` and `allowed_users`, policy-level identity scopes, and per-object scopes restrict which mapped context can act.

Admin credentials are stored separately in `identity.admin_credentials` and must have the `admin` role. They authorize `/admin/approvals`, `/admin/policy`, `/admin/tokens/*`, and `/metrics`. An agent token cannot access those routes.

Local hash rotation/revocation APIs change process memory. They do not update YAML and their effects are lost on restart; persist the new hash securely in deployment configuration.

## Signed JWT validation

Install the project optional auth package into the virtual environment:

```bash
.venv/bin/python -m pip install -e '.[auth]'
```

Configure exactly one of `jwks_url`, `public_keys`, or `secret`, plus issuer and audience. JWT mode enforces an explicit non-`none` algorithm allowlist, signature, issuer, audience, required `exp`, optional `nbf`, required scopes, and claim types. Defaults map agent to `agent_id`, tenant to `tenant_id`, user to `sub`, roles to a string list in `roles`, and scopes to a space-separated `scope` claim (a string list is also accepted).

If a JWT omits tenant/user/roles, tenant and user fall back to the configured agent values, roles to an empty list. Use an identity provider token with short expiry and the correct audience/scopes. `jti` revocation is volatile. JWKS requests occur when token verification needs a key and must be allowed to reach the configured HTTPS identity endpoint.

This is JWT resource-server validation only. MCP-Guard does not implement OAuth 2.1 token issuance, authorization-code flow, OIDC discovery, dynamic client registration, login, or refresh tokens.

## Mutual TLS

Set `http.tls_cert_file` and `http.tls_key_file` for gateway HTTPS. Configure `http.client_ca_file` and `http.require_client_certificate: true` to require client certificates. Test the complete chain and client trust configuration in the target deployment; mTLS supplements HTTP identity and does not replace policy authorization.

## Upstream credentials

MCP upstream credentials live in `http.upstream_headers`; REST action credentials live on each pinned action. These are administrator-owned values (typically `${ENV_VAR}`), separate from the client token. Do not put agent bearer tokens or credentials in URLs.

## Admin authentication and endpoints

Admin token is passed as a bearer token. The admin API includes:

- `GET /admin/approvals?state=pending`
- `POST /admin/approvals/{approval_id}/decision` with `{"decision":"approve"|"reject"}`
- `GET /admin/policy`, `PUT /admin/policy`, and `POST /admin/policy/rollback/{version}`
- `POST /admin/tokens/revoke` with exactly one of `token_hash` or JWT `jti`
- `POST /admin/tokens/rotate` with `old_token_hash` and `new_token_hash` (agent tokens only)
- `GET /metrics`

Admin token hashes are never returned by the policy API. Admin login and role management are not provided; provision separate admin tokens through secure configuration management.
