"""Unit tests for the message validator."""

from __future__ import annotations

from mcp_guard.core.models import JSONRPCMessage
from mcp_guard.protocol.validator import MessageValidator


class TestMessageValidator:
    def test_valid_request(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage(id=1, method="ping")
        ok, reason = v.validate_structure(msg)
        assert ok is True

    def test_valid_response(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage(id=1, result={"ok": True})
        ok, reason = v.validate_structure(msg)
        assert ok is True

    def test_invalid_version(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage(jsonrpc="1.0", id=1, method="ping")
        ok, reason = v.validate_structure(msg)
        assert ok is False
        assert "version" in (reason or "").lower()

    def test_no_method_no_id(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage()
        ok, reason = v.validate_structure(msg)
        assert ok is False

    def test_size_limit(self) -> None:
        v = MessageValidator(max_message_size=100)
        ok, reason = v.validate_size("x" * 200)
        assert ok is False
        assert "exceeds" in (reason or "").lower()

    def test_size_ok(self) -> None:
        v = MessageValidator(max_message_size=1000)
        ok, reason = v.validate_size("small")
        assert ok is True

    def test_validate_request(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage(id=1, method="test")
        ok, reason = v.validate_request(msg)
        assert ok is True

    def test_validate_request_no_method(self) -> None:
        v = MessageValidator()
        msg = JSONRPCMessage(id=1, result={})
        ok, reason = v.validate_request(msg)
        assert ok is False
