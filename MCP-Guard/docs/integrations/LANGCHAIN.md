# LangChain and LangGraph

LangChain's official `langchain-mcp-adapters` client connects to MCP-Guard using Streamable HTTP. Use a bearer token mapped to the intended MCP-Guard agent/tenant/user context; do not ask the model to provide identity claims.

```python
import os

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient


async def run_agent(model) -> None:
    client = MultiServerMCPClient(
        {
            "guarded_customers": {
                "transport": "http",
                "url": os.environ["MCP_GUARD_URL"].rstrip("/") + "/mcp",
                "headers": {
                    "Authorization": f"Bearer {os.environ['MCP_GUARD_AGENT_TOKEN']}"
                },
            }
        }
    )
    tools = await client.get_tools()
    agent = create_agent(model, tools)
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Look up customer C001."}]}
    )
    print(result["messages"][-1].content)
```

`tools/list` is filtered for the authenticated identity. An attempted unauthorized tool call is denied server-side even if a client caches a stale tool list. For a current MCP client that performs `server/discover`, add `methods: {server/discover: allow}` to that agent/server policy.

This same MCP adapter works in LangGraph workflows that consume LangChain tools; direct Python tool functions must call the [MCP-Guard SDK](../SDK.md) or they bypass the MCP proxy.

Reference: [LangChain MCP adapter reference](https://reference.langchain.com/python/langchain-mcp-adapters).
