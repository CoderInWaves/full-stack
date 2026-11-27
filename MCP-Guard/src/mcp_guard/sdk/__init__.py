"""Python SDK for routing MCP and direct REST actions through MCP-Guard."""

from mcp_guard.sdk.client import MCPGuard
from mcp_guard.sdk.errors import (
    MCPGuardApprovalRequired,
    MCPGuardApprovalRequiredError,
    MCPGuardAuthenticationError,
    MCPGuardAuthorizationError,
    MCPGuardError,
    MCPGuardProtocolError,
    MCPGuardTransportError,
)

__all__ = [
    "MCPGuard",
    "MCPGuardApprovalRequired",
    "MCPGuardApprovalRequiredError",
    "MCPGuardAuthenticationError",
    "MCPGuardAuthorizationError",
    "MCPGuardError",
    "MCPGuardProtocolError",
    "MCPGuardTransportError",
]
