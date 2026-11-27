"""Unit tests for the message inspector."""

from __future__ import annotations

import pytest

from mcp_guard.core.models import JSONRPCMessage
from mcp_guard.protocol.inspector import MessageInspector


@pytest.fixture
def inspector() -> MessageInspector:
    return MessageInspector()


class TestMessageInspector:
    def test_tools_call_is_security_relevant(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="tools/call", params={"name": "test"})
        assert inspector.is_security_relevant(msg) is True

    def test_initialize_is_not_security_relevant(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="initialize")
        assert inspector.is_security_relevant(msg) is False

    def test_ping_is_not_security_relevant(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="ping")
        assert inspector.is_security_relevant(msg) is False

    def test_notification_is_not_security_relevant(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(method="notifications/initialized")
        assert inspector.is_security_relevant(msg) is False

    def test_extract_tool_call(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(
            id=5,
            method="tools/call",
            params={"name": "get_customer", "arguments": {"customer_id": "C001"}},
        )
        info = inspector.extract_tool_call(msg, "server1", "agent1")
        assert info is not None
        assert info.tool_name == "get_customer"
        assert info.arguments == {"customer_id": "C001"}
        assert info.request_id == 5
        assert info.server_name == "server1"
        assert info.agent_id == "agent1"

    def test_extract_tool_call_no_arguments(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="tools/call", params={"name": "list_all"})
        info = inspector.extract_tool_call(msg)
        assert info is not None
        assert info.arguments == {}

    def test_extract_non_tool_call(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="ping")
        assert inspector.extract_tool_call(msg) is None

    def test_tools_list_response_filtering(self, inspector: MessageInspector) -> None:
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "get_customer", "description": "Get"},
                    {"name": "delete_customer", "description": "Delete"},
                    {"name": "search_customer", "description": "Search"},
                ]
            },
        }
        filtered = inspector.filter_tools_list_response(
            response, ["get_customer", "search_customer"]
        )
        tools = filtered["result"]["tools"]
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "get_customer" in names
        assert "search_customer" in names
        assert "delete_customer" not in names

    def test_tools_list_response_no_filter(self, inspector: MessageInspector) -> None:
        response = {"result": {"tools": [{"name": "a"}, {"name": "b"}]}}
        filtered = inspector.filter_tools_list_response(response, None)
        assert len(filtered["result"]["tools"]) == 2

    def test_is_initialize(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="initialize")
        assert inspector.is_initialize(msg) is True

    def test_is_tools_list(self, inspector: MessageInspector) -> None:
        msg = JSONRPCMessage(id=1, method="tools/list")
        assert inspector.is_tools_list(msg) is True

    def test_validate_jsonrpc(self, inspector: MessageInspector) -> None:
        good = JSONRPCMessage(id=1, method="ping")
        assert inspector.validate_jsonrpc(good) is True

        bad = JSONRPCMessage(jsonrpc="1.0", id=1, method="ping")
        assert inspector.validate_jsonrpc(bad) is False
