"""Unit tests for the message router."""

from __future__ import annotations

import json

from mcp_guard.core.models import GatewayConfig
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.security.tool_controller import ToolAccessController
from tests.conftest import make_jsonrpc_request, make_tool_call_request


class TestMessageRouter:
    def _make_router(self, config: GatewayConfig) -> MessageRouter:
        tc = ToolAccessController(config)
        return MessageRouter(config, tc)

    def test_allowed_tool_call_forwarded(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        raw = make_tool_call_request("get_customer", {"customer_id": "C001"}, req_id=1)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is not None
        assert error is None

    def test_denied_tool_call_blocked(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        raw = make_tool_call_request("delete_customer", {"customer_id": "C001"}, req_id=2)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None
        assert error is not None
        error_data = json.loads(error)
        assert error_data["id"] == 2
        assert error_data["error"]["code"] == -32001

    def test_non_security_method_passes_through(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        raw = make_jsonrpc_request("initialize", {"capabilities": {}})
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is not None
        assert error is None

    def test_notification_passes_through(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        # Notifications are non-request so pass through
        assert forward is not None

    def test_tools_call_notification_is_rejected(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        raw = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "delete_customer", "arguments": {}},
            }
        )
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None
        assert error is not None

    def test_jsonrpc_batch_is_rejected_without_forwarding(
        self, sample_config: GatewayConfig
    ) -> None:
        router = self._make_router(sample_config)
        raw = '[{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_customer"}}]'
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None
        assert error is not None

    def test_malformed_json_rejected(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        forward, error = router.process_request("{bad json", "agent", "server")
        assert forward is None
        assert error is not None
        assert "Parse error" in error

    def test_oversized_message_rejected(self, sample_config: GatewayConfig) -> None:
        sample_config.security.max_message_size = 50
        router = self._make_router(sample_config)
        raw = make_tool_call_request("test", {"data": "x" * 100}, req_id=3)
        forward, error = router.process_request(raw, "agent", "server")
        assert forward is None
        assert error is not None

    def test_response_id_preserved(self, sample_config: GatewayConfig) -> None:
        """When a request is denied, the error response must preserve the request ID."""
        router = self._make_router(sample_config)
        raw = make_tool_call_request("delete_customer", {}, req_id=99)
        _, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert error is not None
        assert json.loads(error)["id"] == 99

    def test_unknown_method_passes_through(self, sample_config: GatewayConfig) -> None:
        """Unknown valid methods must be forwarded unchanged."""
        router = self._make_router(sample_config)
        raw = make_jsonrpc_request("resources/list", {}, req_id=10)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is not None
        assert error is None

    def test_tools_list_response_filtered(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {"name": "get_customer"},
                        {"name": "delete_customer"},
                        {"name": "search_customer"},
                    ]
                },
            }
        )
        processed = router.process_response(
            response, "support-agent-01", "customer_database", "tools/list"
        )
        data = json.loads(processed)
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "get_customer" in tool_names
        assert "search_customer" in tool_names
        assert "delete_customer" not in tool_names
