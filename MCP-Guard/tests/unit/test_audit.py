"""Unit tests for the audit logger."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_guard.audit.logger import AuditLogger, _sanitize_log_value
from mcp_guard.audit.rotation import rotate_log_file
from mcp_guard.core.constants import DECISION_ALLOW, DECISION_DENY
from mcp_guard.core.models import GatewayConfig, SecurityDecision


class TestAuditLogger:
    def test_rotation_keeps_bounded_extension_named_backups(self, tmp_log_dir: Path) -> None:
        active = tmp_log_dir / "audit.jsonl"
        active.write_text("current", encoding="utf-8")
        (tmp_log_dir / "audit.jsonl.1").write_text("older", encoding="utf-8")

        rotate_log_file(str(active), max_size_mb=0, backup_count=2)

        assert (tmp_log_dir / "audit.jsonl.1").read_text(encoding="utf-8") == "current"
        assert (tmp_log_dir / "audit.jsonl.2").read_text(encoding="utf-8") == "older"
        assert not active.exists()

    def test_log_decision(self, sample_config: GatewayConfig, tmp_log_dir: Path) -> None:
        sample_config.logging.file = str(tmp_log_dir / "test_audit.jsonl")
        logger = AuditLogger(sample_config)

        decision = SecurityDecision(
            allowed=False,
            decision=DECISION_DENY,
            reason_code="TOOL_DENIED",
            reason_message="Tool denied",
            agent_id="support-agent-01",
            server_name="customer_database",
            tool_name="delete_customer",
            latency_ms=1.5,
        )
        logger.log_decision(decision, method="tools/call", request_id=42)
        logger.close()

        log_path = tmp_log_dir / "test_audit.jsonl"
        assert log_path.exists()

        with open(log_path) as f:
            line = f.readline()
            event = json.loads(line)

        assert event["agent_id"] == "support-agent-01"
        assert event["server"] == "customer_database"
        assert event["tool"] == "delete_customer"
        assert event["decision"] == DECISION_DENY
        assert event["reason_code"] == "TOOL_DENIED"
        assert event["request_id"] == 42
        assert "timestamp" in event

    def test_log_access(self, sample_config: GatewayConfig, tmp_log_dir: Path) -> None:
        sample_config.logging.file = str(tmp_log_dir / "test_access.jsonl")
        logger = AuditLogger(sample_config)

        logger.log_access(
            agent_id="support-agent-01",
            server="customer_database",
            method="tools/call",
            decision=DECISION_ALLOW,
            tool="get_customer",
            request_id=1,
        )
        logger.close()

        log_path = tmp_log_dir / "test_access.jsonl"
        with open(log_path) as f:
            event = json.loads(f.readline())

        assert event["decision"] == DECISION_ALLOW
        assert event["tool"] == "get_customer"

    def test_no_secrets_in_logs(self, sample_config: GatewayConfig, tmp_log_dir: Path) -> None:
        """Verify that secrets/tokens are not logged."""
        sample_config.logging.file = str(tmp_log_dir / "test_secrets.jsonl")
        logger = AuditLogger(sample_config)

        decision = SecurityDecision(
            allowed=True,
            decision=DECISION_ALLOW,
            agent_id="agent-01",
            server_name="server",
            tool_name="tool",
        )
        logger.log_decision(decision)
        logger.close()

        with open(tmp_log_dir / "test_secrets.jsonl") as f:
            content = f.read()

        assert "password" not in content.lower()
        assert "secret" not in content.lower()
        assert "token" not in content.lower() or "REDACTED" in content

    def test_sanitize_log_injection(self) -> None:
        """Test that control characters are stripped from log values."""
        malicious = 'agent\n{"injected": true}\r\x00'
        sanitized = _sanitize_log_value(malicious)
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\x00" not in sanitized

    def test_logging_failure_does_not_crash(self, sample_config: GatewayConfig) -> None:
        """Logging failures should be handled gracefully."""
        sample_config.logging.file = "/nonexistent/path/audit.jsonl"
        # Should not raise
        logger = AuditLogger(sample_config)
        decision = SecurityDecision(
            allowed=True, decision=DECISION_ALLOW, agent_id="a", server_name="s", tool_name="t"
        )
        logger.log_decision(decision)  # Should not crash
        logger.close()
