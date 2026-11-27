# OpenAI Agents SDK

The Python Agents SDK provides `MCPServerStreamableHttp`. Configure the MCP-Guard URL and bearer header explicitly:

```python
import asyncio
import os

from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp


async def main() -> None:
    async with MCPServerStreamableHttp(
        name="MCP-Guard",
        params={
            "url": os.environ["MCP_GUARD_URL"].rstrip("/") + "/mcp",
            "headers": {
                "Authorization": f"Bearer {os.environ['MCP_GUARD_AGENT_TOKEN']}"
            },
            "timeout": 15,
        },
        cache_tools_list=False,
    ) as guarded_server:
        agent = Agent(
            name="Customer support",
            instructions="Use the MCP tools for authorized customer lookups.",
            mcp_servers=[guarded_server],
        )
        result = await Runner.run(agent, "Look up customer C001.")
        print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
```

Configure `server/discover` explicitly if the installed MCP SDK v2 performs modern discovery. For a destructive tool, the gateway's approval policy is authoritative; the SDK's local approval option is separate and does not replace MCP-Guard's server decision. Ensure the application can surface the gateway approval ID and retry the same call, or leave the action denied.

Reference: [OpenAI Agents SDK MCP guide](https://openai.github.io/openai-agents-python/mcp/) and [Streamable HTTP API reference](https://openai.github.io/openai-agents-python/ref/mcp/server/).
