# CrewAI

Current CrewAI MCP configuration supports a Streamable HTTP server through `MCPServerHTTP`. Give each permission domain a token mapped to its own policy identity.

```python
import os

from crewai import Agent
from crewai.mcp import MCPServerHTTP

guarded = MCPServerHTTP(
    url=os.environ["MCP_GUARD_URL"].rstrip("/") + "/mcp",
    headers={"Authorization": f"Bearer {os.environ['MCP_GUARD_READ_TOKEN']}"},
    streamable=True,
)

reader = Agent(
    role="Customer reader",
    goal="Read authorized customer records",
    backstory="Only use the tools exposed through MCP-Guard.",
    mcps=[guarded],
)
```

For a separate write-capable agent, create another MCP connection with a different identity token and policy. Do not share a broad token merely because agents are in the same crew. MCP-Guard checks each call independently; a CrewAI tool list is not the security boundary.

Add the `server/discover` method grant if your current CrewAI MCP client probes it. Approval-required actions need an application flow that surfaces the gateway approval ID and retries the exact operation; CrewAI's local approval setting does not approve an MCP-Guard decision.

Reference: [CrewAI MCP overview](https://github.com/crewAIInc/crewAI/blob/main/docs/v1.15.0/en/mcp/overview.mdx).
