"""MCP message validator — checks structural validity of messages."""

from __future__ import annotations

from typing import Optional

from mcp_guard.core.constants import DEFAULT_MAX_MESSAGE_SIZE
from mcp_guard.core.models import JSONRPCMessage


class MessageValidator:
    """Validates MCP protocol messages for structural correctness."""

    def __init__(self, max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE) -> None:
        self.max_message_size = max_message_size

    def validate_size(self, raw: bytes | str) -> tuple[bool, Optional[str]]:
        """Check if a message exceeds the configured size limit."""
        size = len(raw) if isinstance(raw, bytes) else len(raw.encode("utf-8"))
        if size > self.max_message_size:
            return False, f"Message size {size} exceeds limit {self.max_message_size}"
        return True, None

    def validate_structure(self, msg: JSONRPCMessage) -> tuple[bool, Optional[str]]:
        """Validate basic JSON-RPC 2.0 structure."""
        if msg.jsonrpc != "2.0":
            return False, f"Invalid jsonrpc version: {msg.jsonrpc}"

        # A message must be a request, notification, or response
        has_method = msg.method is not None
        has_result = msg.has_result
        has_error = msg.has_error
        has_id = msg.has_id

        if has_method:
            # Request or notification - ok
            if has_result or has_error:
                return False, "Request/notification must not have result or error"
            if not isinstance(msg.method, str) or not msg.method:
                return False, "Request method must be a non-empty string"
            if has_id and (
                msg.id is None
                or isinstance(msg.id, bool)
                or not isinstance(msg.id, (str, int, float))
            ):
                return False, "Request ID must be a string or number"
        elif has_id:
            # Response - must have result XOR error
            if has_result and has_error:
                return False, "Response must not have both result and error"
            if has_result == has_error:
                return False, "Response must have result or error"
        else:
            return False, "Message has neither method nor id"

        return True, None

    def validate_request(self, msg: JSONRPCMessage) -> tuple[bool, Optional[str]]:
        """Validate that a message is a proper request."""
        if not msg.is_request:
            return False, "Not a request (missing method or id)"
        if not isinstance(msg.method, str) or not msg.method:
            return False, "Request method must be a non-empty string"
        return True, None

    def collect_issues(self, raw: str, msg: JSONRPCMessage) -> list[str]:
        """Collect all validation issues for diagnostics."""
        issues: list[str] = []

        ok, reason = self.validate_size(raw)
        if not ok and reason:
            issues.append(reason)

        ok, reason = self.validate_structure(msg)
        if not ok and reason:
            issues.append(reason)

        return issues
