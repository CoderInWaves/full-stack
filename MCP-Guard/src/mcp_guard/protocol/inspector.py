"""MCP message inspector — extracts security-relevant info from MCP messages."""

from __future__ import annotations

from typing import Any, Optional

from mcp_guard.core.constants import (
    METHOD_INITIALIZE,
    METHOD_TOOLS_CALL,
    METHOD_TOOLS_LIST,
    RESPONSE_FILTER_METHODS,
    SECURITY_METHODS,
)
from mcp_guard.core.models import JSONRPCMessage, ToolCallInfo
from mcp_guard.security.validation import validate_tool_name


class MessageInspector:
    """Inspects MCP JSON-RPC messages and extracts security-relevant data."""

    def is_security_relevant(self, msg: JSONRPCMessage) -> bool:
        """Check if this message requires security evaluation."""
        return msg.is_request and msg.method in SECURITY_METHODS

    def is_response_filterable(self, method: Optional[str]) -> bool:
        """Check if the response to this method needs filtering."""
        return method in RESPONSE_FILTER_METHODS

    def extract_tool_call(
        self, msg: JSONRPCMessage, server_name: str = "", agent_id: str = ""
    ) -> Optional[ToolCallInfo]:
        """Extract tool call information from a tools/call request.

        Args:
            msg: The parsed JSON-RPC message.
            server_name: The upstream server name.
            agent_id: The verified agent identity.

        Returns:
            ToolCallInfo if this is a tools/call request, None otherwise.
        """
        if msg.method != METHOD_TOOLS_CALL:
            return None

        if msg.params is None:
            return None

        tool_name = msg.params.get("name")
        valid_name, _ = validate_tool_name(tool_name)
        if not valid_name or not isinstance(tool_name, str):
            return None

        arguments = msg.params.get("arguments", {})
        if not isinstance(arguments, dict):
            return None

        return ToolCallInfo(
            request_id=msg.id,
            tool_name=tool_name,
            arguments=arguments,
            server_name=server_name,
            agent_id=agent_id,
        )

    def is_initialize(self, msg: JSONRPCMessage) -> bool:
        """Check if this is an initialization request."""
        return msg.method == METHOD_INITIALIZE

    def is_tools_list(self, msg: JSONRPCMessage) -> bool:
        """Check if this is a tools/list request."""
        return msg.method == METHOD_TOOLS_LIST

    def filter_tools_list_response(
        self, response_data: dict[str, Any], allowed_tools: Optional[list[str]]
    ) -> dict[str, Any]:
        """Filter a tools/list response to only include allowed tools.

        Args:
            response_data: The raw response dict.
            allowed_tools: List of tool names to keep, or None to keep all.

        Returns:
            Filtered response data.
        """
        if allowed_tools is None:
            return response_data

        result = response_data.get("result")
        if not isinstance(result, dict):
            return response_data

        tools = result.get("tools", [])
        if not isinstance(tools, list):
            return response_data

        filtered_tools = [
            t for t in tools if isinstance(t, dict) and t.get("name") in allowed_tools
        ]

        # Create new response preserving structure
        new_result = dict(result)
        new_result["tools"] = filtered_tools
        new_data = dict(response_data)
        new_data["result"] = new_result
        return new_data

    def get_method_and_id(self, msg: JSONRPCMessage) -> tuple[Optional[str], Optional[Any]]:
        """Extract method and request ID from a message."""
        return msg.method, msg.id

    def validate_jsonrpc(self, msg: JSONRPCMessage) -> bool:
        """Check basic JSON-RPC 2.0 validity."""
        if msg.jsonrpc != "2.0":
            return False
        # Must be request, notification, or response
        if msg.method is None and msg.id is None:
            return False
        return True
