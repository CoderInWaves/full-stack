# Google Agent Development Kit (ADK)

ADK's `McpToolset` supports Streamable HTTP connection parameters and headers. Configure a token mapped to the required MCP-Guard identity:

```python
import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

guarded_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=os.environ["MCP_GUARD_URL"].rstrip("/") + "/mcp",
        headers={
            "Authorization": f"Bearer {os.environ['MCP_GUARD_AGENT_TOKEN']}"
        },
    )
)

root_agent = Agent(
    name="customer_support",
    model=os.environ.get("ADK_MODEL", "gemini-2.5-flash"),
    instruction="Use MCP-Guard tools for authorized customer lookups.",
    tools=[guarded_tools],
)
```

Confirm the exact ADK and MCP package versions in your application environment. Add explicit `server/discover` policy if that client probes the method. MCP-Guard's server-side policy applies to every operation regardless of the agent's displayed tool list.

Reference: [Google ADK MCP tools](https://github.com/google/adk-docs/blob/main/docs/tools-custom/mcp-tools.md).
