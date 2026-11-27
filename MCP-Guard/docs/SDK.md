# Python SDK

The SDK is a small synchronous HTTP client. It delegates every protected decision to MCP-Guard; it does not implement its own authorization engine.

```python
from mcp_guard import MCPGuard
from mcp_guard.sdk import MCPGuardApprovalRequired

with MCPGuard(
    "https://guard.example.internal",
    api_key="agent-token-from-secret-store",
    timeout=15,
) as guard:
    tools = guard.list_tools()
    update_args = {"customer_id": "C001", "status": "active"}
    try:
        result = guard.call_tool("update_customer", update_args)
    except MCPGuardApprovalRequired as pending:
        print("Ask an administrator to approve:", pending.approval_id)
        # After approval, retry the same tool and arguments:
        # result = guard.call_tool("update_customer", update_args, approval_id=pending.approval_id)
```

`MCPGuard.call_tool` and `.request` use Streamable HTTP `/mcp` with the current protocol headers. `.call_action` uses the pinned REST action route. Both use the configured bearer token and surface typed authentication, authorization, approval, protocol, and transport exceptions. The client uses a request timeout, does not auto-retry non-idempotent writes, and does not log credentials.

## Wrapping Python functions

```python
protected = guard.protect(["lookup_customer", "update_customer"])
result = protected["lookup_customer"](customer_id="C001")
```

These wrappers send to `POST /api/v1/actions/{action}`; they intentionally do not call a supplied local function body. Each name must exist in `http.rest_actions`, with the matching policy and server assignment. If a framework invokes direct Python callables, use these wrappers or a framework adapter around `guard.call_action`; calling the original function directly bypasses MCP-Guard.

See [REST API](REST_API.md) and the [framework integration examples](integrations/).
