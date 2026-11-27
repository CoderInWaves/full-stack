import{c as e,g as t,h as n,m as r,o as i,y as a}from"./ui-_sfY2he9.js";import{t as o}from"./copy-DkseZPCO.js";var s=r(`book-open-text`,[[`path`,{d:`M12 7v14`,key:`1akyts`}],[`path`,{d:`M16 12h2`,key:`7q9ll5`}],[`path`,{d:`M16 8h2`,key:`msurwy`}],[`path`,{d:`M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z`,key:`ruj8y`}],[`path`,{d:`M6 12h2`,key:`32wvfc`}],[`path`,{d:`M6 8h2`,key:`30oboj`}]]),c=r(`external-link`,[[`path`,{d:`M15 3h6v6`,key:`1q9fwt`}],[`path`,{d:`M10 14 21 3`,key:`gplh6r`}],[`path`,{d:`M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6`,key:`a6xqqp`}]]),l=r(`square-terminal`,[[`path`,{d:`m7 11 2-2-2-2`,key:`1lz0vl`}],[`path`,{d:`M11 13h4`,key:`1p7l4v`}],[`rect`,{width:`18`,height:`18`,x:`3`,y:`3`,rx:`2`,ry:`2`,key:`1m3agn`}]]),u=a(t(),1),d=n(),f=[{name:`LangChain / LangGraph`,status:`Documented example`,source:`docs/integrations/LANGCHAIN.md`,href:`https://reference.langchain.com/python/langchain-mcp-adapters`,setup:`Connect with the official MCP adapter over Streamable HTTP. Supply an agent bearer token mapped to the intended policy identity.`,code:`from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "guarded": {
        "transport": "http",
        "url": MCP_GUARD_URL.rstrip("/") + "/mcp",
        "headers": {"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},
    }
})
tools = await client.get_tools()`},{name:`OpenAI Agents SDK`,status:`Documented example`,source:`docs/integrations/OPENAI_AGENTS.md`,href:`https://openai.github.io/openai-agents-python/mcp/`,setup:`Use MCPServerStreamableHttp and pass the MCP-Guard URL and bearer header. Surface approval IDs in your application if approval-required actions are used.`,code:`from agents.mcp import MCPServerStreamableHttp

server = MCPServerStreamableHttp(
    name="MCP-Guard",
    params={
        "url": MCP_GUARD_URL.rstrip("/") + "/mcp",
        "headers": {"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},
    },
)`},{name:`CrewAI`,status:`Documented example`,source:`docs/integrations/CREWAI.md`,href:`https://github.com/crewAIInc/crewAI/blob/main/docs/v1.15.0/en/mcp/overview.mdx`,setup:`Configure MCPServerHTTP with Streamable HTTP. Use separate least-privilege identities for different permission domains.`,code:`from crewai.mcp import MCPServerHTTP

guarded = MCPServerHTTP(
    url=MCP_GUARD_URL.rstrip("/") + "/mcp",
    headers={"Authorization": f"Bearer {MCP_GUARD_READ_TOKEN}"},
    streamable=True,
)`},{name:`Google ADK`,status:`Documented example`,source:`docs/integrations/GOOGLE_ADK.md`,href:`https://github.com/google/adk-docs/blob/main/docs/tools-custom/mcp-tools.md`,setup:`Use ADK McpToolset with StreamableHTTPConnectionParams. Verify package versions and explicitly grant server/discover if the client probes it.`,code:`from google.adk.tools.mcp_tool import (
    McpToolset, StreamableHTTPConnectionParams,
)

guarded = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_GUARD_URL.rstrip("/") + "/mcp",
        headers={"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},
    )
)`},{name:`Python SDK`,status:`Included in package`,source:`docs/SDK.md`,href:`#sdk`,setup:`The repository SDK calls Streamable HTTP /mcp and the statically configured REST action gateway. It delegates authorization to MCP-Guard.`,code:`from mcp_guard import MCPGuard

with MCPGuard(MCP_GUARD_URL, api_key=MCP_GUARD_AGENT_TOKEN) as guard:
    tools = guard.list_tools()
    result = guard.call_tool("get_customer", {"customer_id": "C001"})`},{name:`REST action gateway`,status:`Backend feature`,source:`docs/REST_API.md`,href:`#rest-api`,setup:`Call only action names pinned in server configuration. The caller cannot supply an upstream URL or HTTP method; requests reuse MCP identity, policy, DLP and approval checks.`,code:`curl -X POST "$MCP_GUARD_URL/api/v1/actions/get_customer" \\
   -H "Authorization: Bearer $MCP_GUARD_AGENT_TOKEN" \\
   -H "Content-Type: application/json" \\
   -d '{"customer_id":"C001"}'`}];function p({item:t}){let[n,r]=(0,u.useState)(!1),[i,a]=(0,u.useState)(``),f=async()=>{try{await navigator.clipboard.writeText(t.code),r(!0),a(``),window.setTimeout(()=>r(!1),1500)}catch{a(`Clipboard unavailable`)}};return(0,d.jsxs)(`article`,{className:`integration-card`,children:[(0,d.jsxs)(`div`,{className:`integration-top`,children:[(0,d.jsx)(`div`,{className:`integration-icon`,children:(0,d.jsx)(l,{size:19})}),(0,d.jsx)(e,{value:t.status})]}),(0,d.jsx)(`h2`,{children:t.name}),(0,d.jsx)(`p`,{children:t.setup}),(0,d.jsxs)(`div`,{className:`snippet-top`,children:[(0,d.jsx)(`span`,{children:`CONFIGURATION EXAMPLE`}),(0,d.jsxs)(`button`,{className:`copy-button`,onClick:()=>void f(),children:[(0,d.jsx)(o,{size:13}),n?`Copied`:i||`Copy`]})]}),(0,d.jsx)(`pre`,{className:`snippet`,children:(0,d.jsx)(`code`,{children:t.code})}),(0,d.jsxs)(`div`,{className:`integration-footer`,children:[(0,d.jsxs)(`span`,{children:[(0,d.jsx)(s,{size:13}),t.source]}),t.href.startsWith(`https:`)&&(0,d.jsxs)(`a`,{href:t.href,target:`_blank`,rel:`noreferrer`,children:[`Reference `,(0,d.jsx)(c,{size:12})]})]})]})}function m(){return(0,d.jsxs)(d.Fragment,{children:[(0,d.jsx)(i,{eyebrow:`DEVELOPER EXPERIENCE`,title:`Integrations`,description:`Connect agent frameworks and direct applications to the existing MCP-Guard HTTP gateway.`}),(0,d.jsxs)(`div`,{className:`callout callout-info`,children:[(0,d.jsx)(s,{size:17}),(0,d.jsx)(`span`,{children:`These examples are taken from this repository’s integration guides. They document connection setup; they do not imply a framework-specific runtime plugin or end-to-end compatibility test.`})]}),(0,d.jsx)(`div`,{className:`integration-grid`,children:f.map(e=>(0,d.jsx)(p,{item:e},e.name))})]})}export{m as Integrations};