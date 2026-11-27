import { useState } from 'react';
import { BookOpenText, Copy, ExternalLink, TerminalSquare } from 'lucide-react';
import { PageHeader, StatusBadge } from '../components/ui';

const guides = [
  {
    name: 'LangChain / LangGraph', status: 'Documented example', source: 'docs/integrations/LANGCHAIN.md',
    href: 'https://reference.langchain.com/python/langchain-mcp-adapters',
    setup: 'Connect with the official MCP adapter over Streamable HTTP. Supply an agent bearer token mapped to the intended policy identity.',
    code: `from langchain_mcp_adapters.client import MultiServerMCPClient\n\nclient = MultiServerMCPClient({\n    "guarded": {\n        "transport": "http",\n        "url": MCP_GUARD_URL.rstrip("/") + "/mcp",\n        "headers": {"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},\n    }\n})\ntools = await client.get_tools()`,
  },
  {
    name: 'OpenAI Agents SDK', status: 'Documented example', source: 'docs/integrations/OPENAI_AGENTS.md',
    href: 'https://openai.github.io/openai-agents-python/mcp/',
    setup: 'Use MCPServerStreamableHttp and pass the MCP-Guard URL and bearer header. Surface approval IDs in your application if approval-required actions are used.',
    code: `from agents.mcp import MCPServerStreamableHttp\n\nserver = MCPServerStreamableHttp(\n    name="MCP-Guard",\n    params={\n        "url": MCP_GUARD_URL.rstrip("/") + "/mcp",\n        "headers": {"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},\n    },\n)`,
  },
  {
    name: 'CrewAI', status: 'Documented example', source: 'docs/integrations/CREWAI.md',
    href: 'https://github.com/crewAIInc/crewAI/blob/main/docs/v1.15.0/en/mcp/overview.mdx',
    setup: 'Configure MCPServerHTTP with Streamable HTTP. Use separate least-privilege identities for different permission domains.',
    code: `from crewai.mcp import MCPServerHTTP\n\nguarded = MCPServerHTTP(\n    url=MCP_GUARD_URL.rstrip("/") + "/mcp",\n    headers={"Authorization": f"Bearer {MCP_GUARD_READ_TOKEN}"},\n    streamable=True,\n)`,
  },
  {
    name: 'Google ADK', status: 'Documented example', source: 'docs/integrations/GOOGLE_ADK.md',
    href: 'https://github.com/google/adk-docs/blob/main/docs/tools-custom/mcp-tools.md',
    setup: 'Use ADK McpToolset with StreamableHTTPConnectionParams. Verify package versions and explicitly grant server/discover if the client probes it.',
    code: `from google.adk.tools.mcp_tool import (\n    McpToolset, StreamableHTTPConnectionParams,\n)\n\nguarded = McpToolset(\n    connection_params=StreamableHTTPConnectionParams(\n        url=MCP_GUARD_URL.rstrip("/") + "/mcp",\n        headers={"Authorization": f"Bearer {MCP_GUARD_AGENT_TOKEN}"},\n    )\n)`,
  },
  {
    name: 'Python SDK', status: 'Included in package', source: 'docs/SDK.md', href: '#sdk',
    setup: 'The repository SDK calls Streamable HTTP /mcp and the statically configured REST action gateway. It delegates authorization to MCP-Guard.',
    code: `from mcp_guard import MCPGuard\n\nwith MCPGuard(MCP_GUARD_URL, api_key=MCP_GUARD_AGENT_TOKEN) as guard:\n    tools = guard.list_tools()\n    result = guard.call_tool("get_customer", {"customer_id": "C001"})`,
  },
  {
    name: 'REST action gateway', status: 'Backend feature', source: 'docs/REST_API.md', href: '#rest-api',
    setup: 'Call only action names pinned in server configuration. The caller cannot supply an upstream URL or HTTP method; requests reuse MCP identity, policy, DLP and approval checks.',
    code: `curl -X POST "$MCP_GUARD_URL/api/v1/actions/get_customer" \\\n   -H "Authorization: Bearer $MCP_GUARD_AGENT_TOKEN" \\\n   -H "Content-Type: application/json" \\\n   -d '{"customer_id":"C001"}'`,
  },
];

function IntegrationCard({ item }: { item: (typeof guides)[number] }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(item.code);
      setCopied(true);
      setCopyError('');
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopyError('Clipboard unavailable');
    }
  };
  return <article className="integration-card"><div className="integration-top"><div className="integration-icon"><TerminalSquare size={19} /></div><StatusBadge value={item.status} /></div><h2>{item.name}</h2><p>{item.setup}</p><div className="snippet-top"><span>CONFIGURATION EXAMPLE</span><button className="copy-button" onClick={() => void copy()}><Copy size={13} />{copied ? 'Copied' : copyError || 'Copy'}</button></div><pre className="snippet"><code>{item.code}</code></pre><div className="integration-footer"><span><BookOpenText size={13} />{item.source}</span>{item.href.startsWith('https:') && <a href={item.href} target="_blank" rel="noreferrer">Reference <ExternalLink size={12} /></a>}</div></article>;
}

export function Integrations() {
  return <>
    <PageHeader eyebrow="DEVELOPER EXPERIENCE" title="Integrations" description="Connect agent frameworks and direct applications to the existing MCP-Guard HTTP gateway." />
    <div className="callout callout-info"><BookOpenText size={17} /><span>These examples are taken from this repository’s integration guides. They document connection setup; they do not imply a framework-specific runtime plugin or end-to-end compatibility test.</span></div>
    <div className="integration-grid">{guides.map((item) => <IntegrationCard item={item} key={item.name} />)}</div>
  </>;
}
