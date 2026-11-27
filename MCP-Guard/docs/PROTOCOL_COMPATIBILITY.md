# MCP Protocol Compatibility

MCP-Guard preserves raw MCP JSON-RPC frames and does not translate between protocol eras.

| Protocol path | Support | Notes |
|---|---|---|
| Current Streamable HTTP `2026-07-28` | Implemented | Validates per-request protocol metadata and mirrored `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, and declared `Mcp-Param-*` values. Modern client discovery methods need explicit policy grants. |
| Legacy Streamable HTTP `2025-11-25`, `2025-06-18`, `2025-03-26` | Implemented as pass-through | Opaque session and protocol-version headers pass through; no protocol translation. |
| STDIO `initialize` handshake | Implemented as pass-through | One configured client and upstream subprocess. |
| Legacy HTTP+SSE `2024-11-05` | Not implemented | No GET event stream or legacy message endpoint. |
| JSON-RPC batch | Rejected | Per-message authorization is not implemented for batches. |

## Protected operations

- `tools/list`, `resources/list`, `resources/templates/list`, and `prompts/list`: filter discovery results to configured grants. A hidden pagination cursor is stripped.
- `tools/call`: explicit tool action, trusted identity scopes, schema validation, DLP, and optional approval.
- `resources/read`: validates and authorizes the exact URI, including directly constructed URIs.
- `prompts/get`: validates prompt name, arguments schema, and response DLP.
- `tasks/get`, `tasks/update`, `tasks/cancel`: require an explicit method grant, a known task owned by the requesting identity, and current authorization of the task's original tool. Task owner records are in-memory.
- `subscriptions/listen`: explicit method grant, filters resource URIs, then filters emitted events and list-changed flags.
- `server/discover`: explicit `methods.server/discover: allow`; returned servers are filtered to policy-configured servers.
- `initialize` and `ping` are narrowly permitted protocol-control requests. Known lifecycle notifications pass; unknown valid request methods/extensions are denied unless explicitly granted. Unknown notifications are dropped unless explicitly granted.

## Client configuration

Some current clients probe `server/discover` before listing tools. Add an explicit method permission under the corresponding agent/server policy:

```yaml
methods:
  server/discover: allow
```

The gateway still filters discovery and checks each later operation. If a client uses another extension, add an explicit method rule only after reviewing the method's behavior.

## HTTP mirrors

For current protocol HTTP, body metadata and method headers must agree. `Mcp-Name` is required for tool calls, resource reads, and prompt retrieval. If a visible tool schema marks a string/integer/boolean property with `x-mcp-header`, the corresponding `Mcp-Param-*` header must match the JSON body. Redactions are applied to both copies before forwarding. Reserved/security-sensitive header names are rejected.
