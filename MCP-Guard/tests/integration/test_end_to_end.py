"""Integration tests for the STDIO transport and end-to-end flow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mcp_guard.core.models import GatewayConfig
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.security.tool_controller import ToolAccessController
from tests.conftest import make_jsonrpc_request, make_tool_call_request

# Path to the demo server
DEMO_SERVER = str(Path(__file__).parent.parent.parent / "examples" / "demo_server.py")


class TestEndToEndRouter:
    """Test the full router pipeline with realistic messages."""

    def _make_router(self, config: GatewayConfig) -> MessageRouter:
        tc = ToolAccessController(config)
        return MessageRouter(config, tc)

    def test_full_allow_flow(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        # 1. Initialize passes through
        init_req = make_jsonrpc_request("initialize", {"capabilities": {}}, req_id=1)
        f, e = router.process_request(init_req, "support-agent-01", "customer_database")
        assert f is not None and e is None

        # 2. tools/list passes through
        list_req = make_jsonrpc_request("tools/list", {}, req_id=2)
        f, e = router.process_request(list_req, "support-agent-01", "customer_database")
        assert f is not None and e is None

        # 3. Allowed tool call passes through
        call_req = make_tool_call_request("get_customer", {"customer_id": "C001"}, req_id=3)
        f, e = router.process_request(call_req, "support-agent-01", "customer_database")
        assert f is not None and e is None

    def test_full_deny_flow(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        # Denied tool call blocked
        call_req = make_tool_call_request("delete_customer", {"customer_id": "C001"}, req_id=10)
        f, e = router.process_request(call_req, "support-agent-01", "customer_database")
        assert f is None
        assert e is not None
        err = json.loads(e)
        assert err["id"] == 10
        assert "denied" in err["error"]["message"].lower() or "denied" in str(err["error"]).lower()

    def test_dlp_on_response(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "result": {"content": [{"type": "text", "text": '{"email": "alice@example.com"}'}]},
            }
        )
        processed = router.process_response(
            response, "support-agent-01", "customer_database", "tools/call"
        )
        assert "alice@example.com" not in processed
        assert "[REDACTED_EMAIL]" in processed

    def test_tools_list_filtering_integration(self, sample_config: GatewayConfig) -> None:
        router = self._make_router(sample_config)
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "get_customer", "description": "Get"},
                        {"name": "search_customer", "description": "Search"},
                        {"name": "delete_customer", "description": "Delete"},
                        {"name": "update_customer", "description": "Update"},
                        {"name": "generate_report", "description": "Report"},
                    ]
                },
            }
        )
        processed = router.process_response(
            response, "support-agent-01", "customer_database", "tools/list"
        )
        data = json.loads(processed)
        tool_names = [t["name"] for t in data["result"]["tools"]]
        # delete_customer is DENY => filtered out
        assert "delete_customer" not in tool_names
        # get_customer, search_customer, generate_report are ALLOW => kept
        assert "get_customer" in tool_names
        assert "search_customer" in tool_names
        assert "generate_report" in tool_names
        # update_customer is APPROVAL_REQUIRED => kept in list (filtered at call time)
        assert "update_customer" in tool_names


class TestDemoServerDirect:
    """Test the demo server directly (no proxy) to verify it works."""

    def test_demo_server_handles_requests(self) -> None:
        """Verify demo_server.py can handle JSON-RPC requests."""
        # Import the demo server's handle_request function
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "examples"))
        try:
            from demo_server import handle_request

            # Test initialize
            resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert resp is not None
            assert resp["id"] == 1
            assert "result" in resp

            # Test tools/list
            resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert resp is not None
            assert len(resp["result"]["tools"]) == 5

            # Test tools/call get_customer
            resp = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_customer", "arguments": {"customer_id": "C001"}},
                }
            )
            assert resp is not None
            assert resp["result"]["isError"] is False
            content = json.loads(resp["result"]["content"][0]["text"])
            assert content["name"] == "Alice Johnson"

        finally:
            sys.path.pop(0)

    def test_demo_server_delete_tracked(self) -> None:
        """Verify delete_customer is tracked in call log."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "examples"))
        try:
            from demo_server import CALL_LOG, handle_request

            initial_len = len(CALL_LOG)
            handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "delete_customer",
                        "arguments": {"customer_id": "C999", "confirm": False},
                    },
                }
            )
            assert len(CALL_LOG) == initial_len + 1
            assert CALL_LOG[-1]["tool"] == "delete_customer"
        finally:
            sys.path.pop(0)


class TestHTTPTransportIntegration:
    """Integration tests for the HTTP transport (using test client)."""

    @pytest.fixture
    def http_app(self, sample_config: GatewayConfig):
        """Create an HTTP transport app for testing."""
        from mcp_guard.transports.http import HTTPTransport

        sample_config.transport = "http"
        from mcp_guard.core.models import HTTPTransportConfig

        sample_config.http = HTTPTransportConfig(
            host="127.0.0.1",
            port=9999,
            upstream_url="",  # No actual upstream for unit test
            allowed_origins=["http://localhost:3000"],
        )
        transport = HTTPTransport(sample_config)
        return transport.create_app()

    @pytest.mark.asyncio
    async def test_health_endpoint(self, http_app) -> None:
        from starlette.testclient import TestClient

        client = TestClient(http_app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unauthenticated_request_denied(self, http_app) -> None:
        from starlette.testclient import TestClient

        client = TestClient(http_app)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_origin_rejected(self, http_app, sample_config: GatewayConfig) -> None:
        from starlette.testclient import TestClient

        # Register a token for testing
        from mcp_guard.identity.manager import IdentityManager

        mgr = IdentityManager(sample_config)
        mgr.register_token("support-agent-01", "test-token")

        client = TestClient(http_app)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={
                "Authorization": "Bearer test-token",
                "Origin": "http://evil.com",
            },
        )
        assert response.status_code == 403
