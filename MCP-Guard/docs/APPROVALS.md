# Human Approval Workflow

The approval backend covers HTTP MCP tool calls and configured REST actions whose policy action is `approval_required`.

## Flow

1. MCP-Guard validates the identity, policy scope, arguments, and request DLP.
2. It queues a redacted request record and returns an approval ID. It does not forward the operation.
3. An independent administrator lists the pending request and approves or rejects it through the admin API or the `/admin` UI.
4. After approval, the caller retries the exact same operation with the approval ID.
5. MCP-Guard verifies the HMAC-bound action and identity, consumes the approval once, and re-evaluates current policy immediately before forwarding.

For MCP, the JSON-RPC error contains `error.data.approval_id`. Retry with HTTP header `Mcp-Guard-Approval-Id` or `params._meta["io.mcp-guard/approvalId"]`. The SDK offers `approval_id=` on `call_tool`. For a REST action, the initial request returns HTTP 202 with `approval_id`; retry the same body with header `Mcp-Guard-Approval-Id` or `MCPGuard.call_action(..., approval_id=...)`.

An approval is tied to the action name, canonical arguments, server, agent, tenant, user, and roles. Changed values, expired/rejected/not-yet-approved IDs, and replay attempts are denied. If policy changes after approval, the current policy is evaluated again.

## APIs

```http
GET /admin/approvals?state=pending
Authorization: Bearer <ADMIN_TOKEN>
```

```http
POST /admin/approvals/<APPROVAL_ID>/decision
Authorization: Bearer <ADMIN_TOKEN>
Content-Type: application/json

{"decision":"approve"}
```

Allowed states are `pending`, `approved`, `rejected`, `expired`, and `consumed`. The queue metadata does not expose arguments by default. Approval decisions are audited with the administrator ID.

## Limits

- Queue, HMAC key, and history are in process memory and disappear on restart.
- Default timeout is 900 seconds; configure `security.approval_timeout_seconds` from 1 to 86400.
- No email, Slack, webhook, or durable notification adapter is implemented.
- Admin APIs require HTTP transport. Approval-required STDIO actions fail closed.
