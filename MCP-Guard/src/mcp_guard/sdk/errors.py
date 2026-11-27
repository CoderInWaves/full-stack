"""Structured errors raised by the MCP-Guard Python SDK."""

from __future__ import annotations

from typing import Any


class MCPGuardError(Exception):
    """Base SDK error with transport and gateway details when available."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.data = data


class MCPGuardAuthenticationError(MCPGuardError):
    """The configured bearer credential was not accepted."""


class MCPGuardAuthorizationError(MCPGuardError):
    """The authenticated identity is not authorized for an action."""


class MCPGuardApprovalRequiredError(MCPGuardAuthorizationError):
    """An administrator must approve the action before it can be retried."""

    def __init__(self, message: str, *, approval_id: str | None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.approval_id = approval_id


MCPGuardApprovalRequired = MCPGuardApprovalRequiredError


class MCPGuardProtocolError(MCPGuardError):
    """The gateway returned malformed or unsupported MCP data."""


class MCPGuardTransportError(MCPGuardError):
    """The gateway could not be reached or returned an unexpected HTTP error."""
