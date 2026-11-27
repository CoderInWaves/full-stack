"""Unit tests for the policy engine."""

from __future__ import annotations

from mcp_guard.core.constants import (
    DECISION_ALLOW,
    DECISION_APPROVAL_REQUIRED,
    DECISION_DENY,
    REASON_APPROVAL_REQUIRED,
    REASON_DISABLED_AGENT,
    REASON_INVALID_ARGUMENTS,
    REASON_MISSING_IDENTITY,
    REASON_SERVER_NOT_ASSIGNED,
    REASON_TOOL_DENIED,
    REASON_TOOL_NOT_ALLOWED,
    REASON_UNKNOWN_AGENT,
)
from mcp_guard.core.models import GatewayConfig, ToolCallInfo
from mcp_guard.policies.engine import PolicyEngine


class TestPolicyEngine:
    def test_allowed_tool(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=1,
            tool_name="get_customer",
            arguments={"customer_id": "C001"},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is True
        assert decision.decision == DECISION_ALLOW

    def test_denied_tool(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=2,
            tool_name="delete_customer",
            arguments={"customer_id": "C001"},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.decision == DECISION_DENY
        assert decision.reason_code == REASON_TOOL_DENIED

    def test_unlisted_tool_denied(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=3,
            tool_name="drop_database",
            arguments={},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_TOOL_NOT_ALLOWED

    def test_missing_identity(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=4,
            tool_name="get_customer",
            arguments={},
            server_name="customer_database",
            agent_id="",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_MISSING_IDENTITY

    def test_unknown_agent(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=5,
            tool_name="get_customer",
            arguments={},
            server_name="customer_database",
            agent_id="nonexistent-agent",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_UNKNOWN_AGENT

    def test_disabled_agent(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=6,
            tool_name="get_customer",
            arguments={},
            server_name="customer_database",
            agent_id="disabled-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_DISABLED_AGENT

    def test_server_not_assigned(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=7,
            tool_name="get_customer",
            arguments={},
            server_name="analytics_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_SERVER_NOT_ASSIGNED

    def test_approval_required(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=8,
            tool_name="update_customer",
            arguments={},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.decision == DECISION_APPROVAL_REQUIRED
        assert decision.reason_code == REASON_APPROVAL_REQUIRED

    def test_argument_validation_pass(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=9,
            tool_name="generate_report",
            arguments={"report_type": "summary"},
            server_name="analytics_database",
            agent_id="report-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is True

    def test_argument_validation_fail(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=10,
            tool_name="generate_report",
            arguments={"report_type": "malicious_type"},
            server_name="analytics_database",
            agent_id="report-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_INVALID_ARGUMENTS

    def test_argument_validation_missing_required(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=11,
            tool_name="generate_report",
            arguments={},
            server_name="analytics_database",
            agent_id="report-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.reason_code == REASON_INVALID_ARGUMENTS

    def test_explicit_deny_overrides(self, sample_config: GatewayConfig) -> None:
        """Explicit deny must override everything for that tool."""
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=12,
            tool_name="delete_customer",
            arguments={},
            server_name="customer_database",
            agent_id="support-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        assert decision.decision == DECISION_DENY

    def test_get_allowed_tools(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        allowed = engine.get_allowed_tools("support-agent-01", "customer_database")
        assert allowed is not None
        assert "get_customer" in allowed
        assert "search_customer" in allowed
        assert "update_customer" in allowed  # approval_required shows in list
        assert "delete_customer" not in allowed

    def test_get_allowed_tools_unknown_agent(self, sample_config: GatewayConfig) -> None:
        engine = PolicyEngine(sample_config)
        allowed = engine.get_allowed_tools("nobody", "customer_database")
        assert allowed == []

    def test_no_policy_for_agent(self, sample_config: GatewayConfig) -> None:
        """Agent exists in identity but no policy defined."""
        engine = PolicyEngine(sample_config)
        call = ToolCallInfo(
            request_id=13,
            tool_name="get_customer",
            arguments={},
            server_name="customer_database",
            agent_id="disabled-agent-01",
        )
        decision = engine.evaluate(call)
        assert decision.allowed is False
        # Disabled agent should be caught first
        assert decision.reason_code == REASON_DISABLED_AGENT
