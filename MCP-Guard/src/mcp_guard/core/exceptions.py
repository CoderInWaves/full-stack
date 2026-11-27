"""Core exceptions for MCP-Guard."""

from __future__ import annotations


class MCPGuardError(Exception):
    """Base exception for all MCP-Guard errors."""


class ConfigurationError(MCPGuardError):
    """Raised when configuration is invalid."""


class PolicyViolationError(MCPGuardError):
    """Raised when a policy check fails."""

    def __init__(self, reason_code: str, message: str, agent_id: str = "", tool: str = "") -> None:
        self.reason_code = reason_code
        self.agent_id = agent_id
        self.tool = tool
        super().__init__(message)


class AuthenticationError(MCPGuardError):
    """Raised when authentication fails."""


class TransportError(MCPGuardError):
    """Raised when a transport-level error occurs."""


class ProtocolError(MCPGuardError):
    """Raised when an MCP protocol message is invalid."""


class DLPViolationError(MCPGuardError):
    """Raised when a DLP pattern is matched and policy is BLOCK."""

    def __init__(self, pattern_name: str, message: str) -> None:
        self.pattern_name = pattern_name
        super().__init__(message)


class UpstreamError(MCPGuardError):
    """Raised when the upstream MCP server fails."""


class TimeoutError(MCPGuardError):  # noqa: A001
    """Raised when an operation times out."""
