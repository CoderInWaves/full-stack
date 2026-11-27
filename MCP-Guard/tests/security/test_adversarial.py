"""Security tests — adversarial and boundary scenarios."""

from __future__ import annotations

import json

import pytest

from mcp_guard.core.models import GatewayConfig, ToolCallInfo
from mcp_guard.policies.engine import PolicyEngine
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.security.tool_controller import ToolAccessController
from tests.conftest import make_tool_call_request


class TestPromptInjectionDefense:
    """Simulate prompt-injection-driven unauthorized tool calls."""

    def test_injection_delete_via_support_agent(self, sample_config: GatewayConfig) -> None:
        """Agent instructed by injection to delete — must be denied."""
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request(
            "delete_customer",
            {"customer_id": "C001", "confirm": True},
            req_id=100,
        )
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None, "Destructive tool call must NOT be forwarded"
        assert error is not None
        err = json.loads(error)
        assert err["id"] == 100
        assert err["error"]["code"] == -32001

    def test_injection_unlisted_tool(self, sample_config: GatewayConfig) -> None:
        """Agent tries to call a tool not in policy — deny by default."""
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request("drop_all_tables", {}, req_id=101)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None
        assert error is not None


class TestIdentitySpoofing:
    """Attempts to access another agent's permissions."""

    def test_support_agent_cannot_use_admin_tools(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        # Support agent tries to use a tool only admin has on customer_database
        # Admin has delete_customer as approval_required, support has it denied
        call = ToolCallInfo(
            request_id=200,
            tool_name="delete_customer",
            arguments={"customer_id": "C001"},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False

    def test_agent_id_from_arguments_not_trusted(self, sample_config: GatewayConfig) -> None:
        """Even if arguments contain agent_id, the verified identity is used."""
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        # Include a fake agent_id in the tool arguments
        raw = make_tool_call_request(
            "delete_customer",
            {"customer_id": "C001", "agent_id": "admin-agent-01"},
            req_id=201,
        )
        # But the verified identity is support-agent-01
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None  # Still denied


class TestMalformedPayloads:
    """Malformed JSON-RPC payloads."""

    def test_completely_invalid_json(self, sample_config: GatewayConfig) -> None:
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        forward, error = router.process_request("{{{{", "agent", "server")
        assert forward is None
        assert error is not None

    def test_missing_method(self, sample_config: GatewayConfig) -> None:
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = json.dumps({"jsonrpc": "2.0", "id": 1})
        forward, error = router.process_request(raw, "agent", "server")
        # This is a response-like message, should be handled
        # It has id but no method, result, or error — invalid structure
        assert forward is None
        assert error is not None

    def test_null_params(self, sample_config: GatewayConfig) -> None:
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": None})
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        # Should handle None params gracefully
        assert error is not None  # Can't extract tool call from None params

    def test_empty_tool_name(self, sample_config: GatewayConfig) -> None:
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request("", {}, req_id=300)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None  # Empty tool name should be denied

    def test_very_long_tool_name(self, sample_config: GatewayConfig) -> None:
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request("a" * 10000, {}, req_id=301)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None  # Unknown tool — denied


class TestOversizedMessages:
    def test_oversized_request(self, sample_config: GatewayConfig) -> None:
        sample_config.security.max_message_size = 200
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request("get_customer", {"data": "x" * 500}, req_id=400)
        forward, error = router.process_request(raw, "agent", "server")
        assert forward is None
        assert error is not None

    def test_oversized_response(self, sample_config: GatewayConfig) -> None:
        sample_config.security.max_message_size = 100
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        big_response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"data": "x" * 500}})
        processed = router.process_response(big_response, "agent", "server")
        data = json.loads(processed)
        assert "error" in data


class TestLogInjection:
    def test_newline_injection_in_agent_id(self, sample_config: GatewayConfig) -> None:
        from mcp_guard.audit.logger import _sanitize_log_value

        malicious = 'agent-01\n{"injected":"true"}'
        sanitized = _sanitize_log_value(malicious)
        assert "\n" not in sanitized

    def test_null_byte_injection(self, sample_config: GatewayConfig) -> None:
        from mcp_guard.audit.logger import _sanitize_log_value

        malicious = "agent\x00injected"
        sanitized = _sanitize_log_value(malicious)
        assert "\x00" not in sanitized


class TestPathTraversal:
    def test_path_traversal_detection(self) -> None:
        from mcp_guard.security.validation import check_path_traversal

        assert check_path_traversal("../../../etc/passwd") is True
        assert check_path_traversal("..\\..\\windows\\system32") is True
        assert check_path_traversal("safe/path/file.txt") is False


class TestDLPSecurity:
    def test_dlp_block_prevents_data_leak(self, sample_config: GatewayConfig) -> None:
        """DLP failure must NOT silently permit sensitive data."""
        from mcp_guard.core.exceptions import DLPViolationError
        from mcp_guard.core.models import DLPMode, DLPPattern
        from mcp_guard.security.dlp import DLPEngine

        sample_config.security.dlp_patterns = [
            DLPPattern(
                name="ssn",
                pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                mode=DLPMode.BLOCK,
                replacement="[BLOCKED]",
            ),
        ]
        engine = DLPEngine(sample_config)
        with pytest.raises(DLPViolationError):
            engine.inspect_message('{"ssn": "123-45-6789"}')


class TestApprovalRequired:
    def test_approval_required_not_forwarded(self, sample_config: GatewayConfig) -> None:
        """Approval-required tools must fail closed."""
        tc = ToolAccessController(sample_config)
        router = MessageRouter(sample_config, tc)
        raw = make_tool_call_request("update_customer", {"customer_id": "C001"}, req_id=500)
        forward, error = router.process_request(raw, "support-agent-01", "customer_database")
        assert forward is None, "Approval-required tool must NOT be forwarded"
        assert error is not None
