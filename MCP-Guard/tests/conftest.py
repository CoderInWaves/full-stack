"""Shared test fixtures for MCP-Guard tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mcp_guard.core.models import (
    AgentIdentity,
    AgentPolicy,
    ArgumentConstraint,
    DLPMode,
    DLPPattern,
    GatewayConfig,
    IdentityConfig,
    LoggingConfig,
    PolicyAction,
    PolicyConfig,
    SecurityConfig,
    ServerPolicy,
    STDIOTransportConfig,
    ToolCallInfo,
    ToolPolicy,
    UpstreamConfig,
)


@pytest.fixture
def tmp_log_dir(tmp_path: Path) -> Path:
    """Create a temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def sample_agents() -> dict[str, AgentIdentity]:
    """Sample agent identities."""
    return {
        "support_agent": AgentIdentity(
            id="support-agent-01",
            name="Customer Support Agent",
            enabled=True,
            servers=["customer_database"],
        ),
        "report_agent": AgentIdentity(
            id="report-agent-01",
            name="Report Generator Agent",
            enabled=True,
            servers=["analytics_database"],
        ),
        "admin_agent": AgentIdentity(
            id="admin-agent-01",
            name="Admin Agent",
            enabled=True,
            servers=["customer_database", "analytics_database"],
        ),
        "disabled_agent": AgentIdentity(
            id="disabled-agent-01",
            name="Disabled Agent",
            enabled=False,
            servers=["customer_database"],
        ),
    }


@pytest.fixture
def sample_policy() -> PolicyConfig:
    """Sample policy configuration."""
    return PolicyConfig(
        default_action=PolicyAction.DENY,
        agents={
            "support-agent-01": AgentPolicy(
                servers={
                    "customer_database": ServerPolicy(
                        enabled=True,
                        tools={
                            "get_customer": ToolPolicy(action=PolicyAction.ALLOW),
                            "search_customer": ToolPolicy(action=PolicyAction.ALLOW),
                            "generate_report": ToolPolicy(action=PolicyAction.ALLOW),
                            "update_customer": ToolPolicy(action=PolicyAction.APPROVAL_REQUIRED),
                            "delete_customer": ToolPolicy(action=PolicyAction.DENY),
                        },
                    )
                }
            ),
            "report-agent-01": AgentPolicy(
                servers={
                    "analytics_database": ServerPolicy(
                        enabled=True,
                        tools={
                            "generate_report": ToolPolicy(
                                action=PolicyAction.ALLOW,
                                argument_constraints=ArgumentConstraint(
                                    json_schema={
                                        "type": "object",
                                        "properties": {
                                            "report_type": {
                                                "type": "string",
                                                "enum": ["summary", "detailed"],
                                            }
                                        },
                                        "required": ["report_type"],
                                    }
                                ),
                            ),
                            "delete_report": ToolPolicy(action=PolicyAction.DENY),
                        },
                    )
                }
            ),
            "admin-agent-01": AgentPolicy(
                servers={
                    "customer_database": ServerPolicy(
                        enabled=True,
                        tools={
                            "get_customer": ToolPolicy(action=PolicyAction.ALLOW),
                            "delete_customer": ToolPolicy(action=PolicyAction.APPROVAL_REQUIRED),
                        },
                    )
                }
            ),
        },
    )


@pytest.fixture
def sample_config(
    tmp_log_dir: Path, sample_agents: dict[str, AgentIdentity], sample_policy: PolicyConfig
) -> GatewayConfig:
    """Full sample configuration."""
    return GatewayConfig(
        name="MCP-Guard Test",
        environment="test",
        transport="stdio",
        default_policy=PolicyAction.DENY,
        stdio=STDIOTransportConfig(
            upstream=UpstreamConfig(
                name="customer_database",
                command=["python3", "examples/demo_server.py"],
            )
        ),
        identity=IdentityConfig(
            agent_id="support-agent-01",
            agents=sample_agents,
        ),
        policy=sample_policy,
        logging=LoggingConfig(
            format="jsonl",
            level="DEBUG",
            file=str(tmp_log_dir / "audit.jsonl"),
        ),
        security=SecurityConfig(
            max_message_size=1048576,
            request_timeout_seconds=30,
            enable_dlp=True,
            dlp_patterns=[
                DLPPattern(
                    name="email",
                    pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    mode=DLPMode.REDACT,
                    replacement="[REDACTED_EMAIL]",
                ),
                DLPPattern(
                    name="api_key",
                    pattern=r"\b(?:sk|pk|api|key|token)[-_][a-zA-Z0-9]{20,}\b",
                    mode=DLPMode.REDACT,
                    replacement="[REDACTED_API_KEY]",
                ),
            ],
        ),
    )


@pytest.fixture
def sample_tool_call() -> ToolCallInfo:
    """Sample allowed tool call."""
    return ToolCallInfo(
        request_id=1,
        tool_name="get_customer",
        arguments={"customer_id": "C001"},
        server_name="customer_database",
        agent_id="support-agent-01",
    )


@pytest.fixture
def denied_tool_call() -> ToolCallInfo:
    """Sample denied tool call."""
    return ToolCallInfo(
        request_id=2,
        tool_name="delete_customer",
        arguments={"customer_id": "C001", "confirm": True},
        server_name="customer_database",
        agent_id="support-agent-01",
    )


def make_jsonrpc_request(method: str, params: dict[str, Any] = None, req_id: int = 1) -> str:
    """Create a JSON-RPC request string."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def make_tool_call_request(
    tool_name: str, arguments: dict[str, Any] = None, req_id: int = 1
) -> str:
    """Create a tools/call JSON-RPC request."""
    return make_jsonrpc_request(
        "tools/call",
        {"name": tool_name, "arguments": arguments or {}},
        req_id,
    )


def make_jsonrpc_response(req_id: int, result: Any = None) -> str:
    """Create a JSON-RPC response string."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if result is not None:
        msg["result"] = result
    else:
        msg["result"] = {}
    return json.dumps(msg)
