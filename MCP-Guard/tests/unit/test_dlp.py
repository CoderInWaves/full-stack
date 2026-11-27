"""Unit tests for the DLP engine."""

from __future__ import annotations

import json

import pytest

from mcp_guard.core.exceptions import ConfigurationError, DLPViolationError
from mcp_guard.core.models import DLPMode, DLPPattern, GatewayConfig, IdentityContext
from mcp_guard.security import dlp as dlp_module
from mcp_guard.security.dlp import DLPEngine


class TestDLPEngine:
    def test_supported_runtime_fails_closed_without_timeout_regex(
        self, sample_config: GatewayConfig, monkeypatch
    ) -> None:
        monkeypatch.setattr(dlp_module, "PYTHON_REQUIRES_TIMEOUT_REGEX", True)
        monkeypatch.setattr(dlp_module, "_REGEX_TIMEOUT_SUPPORTED", False)
        with pytest.raises(ConfigurationError, match="regex dependency is required"):
            DLPEngine(sample_config)

    def test_email_redaction(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"email": "alice@example.com", "name": "Alice"}'
        result = engine.inspect_message(text)
        assert "[REDACTED_EMAIL]" in result
        assert "alice@example.com" not in result
        assert "Alice" in result

    def test_api_key_redaction(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"key": "sk-abc123def456ghi789jkl012mno"}'
        result = engine.inspect_message(text)
        assert "[REDACTED_API_KEY]" in result
        assert "sk-abc123def456ghi789jkl012mno" not in result

    def test_no_match_unchanged(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"message": "Hello, World!", "count": 42}'
        result = engine.inspect_message(text)
        assert result == text

    def test_disabled_dlp(self, sample_config: GatewayConfig) -> None:
        sample_config.security.enable_dlp = False
        engine = DLPEngine(sample_config)
        text = '{"email": "alice@example.com"}'
        result = engine.inspect_message(text)
        assert result == text  # Unchanged when DLP is disabled

    def test_block_mode(self, sample_config: GatewayConfig) -> None:
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

    def test_scan_without_modify(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"email": "test@example.com"}'
        findings = engine.scan_text(text)
        assert len(findings) > 0
        assert findings[0]["pattern"] == "email"

    def test_redact_text(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = "Contact alice@example.com for details"
        result = engine.redact_text(text)
        assert "[REDACTED_EMAIL]" in result

    def test_pattern_scope_matches_agent_server_method_and_direction(
        self, sample_config: GatewayConfig
    ) -> None:
        sample_config.security.dlp_patterns = [
            DLPPattern(
                name="scoped_email",
                pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                replacement="[SCOPED]",
                agents=["support-agent-01"],
                servers=["customer_database"],
                methods=["tools/call"],
                directions=["request"],
            )
        ]
        engine = DLPEngine(sample_config)
        raw = (
            '{"jsonrpc":"2.0","id":1,"method":"tools/call",'
            '"params":{"name":"get_customer","arguments":{"email":"alice@example.com"}}}'
        )

        scoped = engine.inspect_message(
            raw, "support-agent-01", "customer_database", "request", "tools/call"
        )
        out_of_scope = engine.inspect_message(
            raw, "support-agent-01", "customer_database", "response", "tools/call"
        )

        assert "[SCOPED]" in scoped
        assert "alice@example.com" in out_of_scope

    def test_pattern_scope_matches_trusted_tenant_and_user(
        self, sample_config: GatewayConfig
    ) -> None:
        sample_config.security.dlp_patterns = [
            DLPPattern(
                name="tenant_email",
                pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                replacement="[TENANT_REDACTED]",
                tenant_ids=["bank-a"],
                user_ids=["customer-100"],
            )
        ]
        engine = DLPEngine(sample_config)
        raw = '{"message":"alice@example.com"}'
        matching = engine.inspect_message(
            raw,
            "support-agent-01",
            "customer_database",
            context=IdentityContext(
                agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
            ),
        )
        other_tenant = engine.inspect_message(
            raw,
            "support-agent-01",
            "customer_database",
            context=IdentityContext(
                agent_id="support-agent-01", tenant_id="bank-b", user_id="customer-100"
            ),
        )
        assert "[TENANT_REDACTED]" in matching
        assert "alice@example.com" in other_tenant
        assert engine.scan_text(
            "alice@example.com",
            context=IdentityContext(
                agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
            ),
        )
        assert not engine.scan_text(
            "alice@example.com",
            context=IdentityContext(
                agent_id="support-agent-01", tenant_id="bank-b", user_id="customer-100"
            ),
        )
        assert (
            engine.redact_text(
                "alice@example.com",
                context=IdentityContext(
                    agent_id="support-agent-01", tenant_id="bank-a", user_id="customer-100"
                ),
            )
            == "[TENANT_REDACTED]"
        )

    def test_task_result_content_is_inspected(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        raw = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "result": {
                    "taskId": "task-12",
                    "status": "completed",
                    "result": {"content": [{"type": "text", "text": "Contact alice@example.com"}]},
                },
            }
        )
        processed = engine.inspect_message(
            raw, "support-agent-01", "customer_database", "response", "tasks/get"
        )
        assert "alice@example.com" not in processed

    def test_resource_and_prompt_text_blocks_are_inspected(
        self, sample_config: GatewayConfig
    ) -> None:
        engine = DLPEngine(sample_config)
        resource = {
            "jsonrpc": "2.0",
            "id": 10,
            "result": {
                "contents": [
                    {
                        "uri": "file:///customer.txt",
                        "mimeType": "text/plain",
                        "text": "Contact alice@example.com",
                    },
                    {"uri": "file:///image.png", "blob": "YWJj"},
                ]
            },
        }
        prompt = {
            "jsonrpc": "2.0",
            "id": 11,
            "result": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Contact alice@example.com"}],
                    }
                ]
            },
        }

        redacted_resource = engine.inspect_message(
            json.dumps(resource),
            "support-agent-01",
            "customer_database",
            "response",
            "resources/read",
        )
        redacted_prompt = engine.inspect_message(
            json.dumps(prompt),
            "support-agent-01",
            "customer_database",
            "response",
            "prompts/get",
        )

        assert "alice@example.com" not in redacted_resource
        assert '"blob":"YWJj"' in redacted_resource
        assert "alice@example.com" not in redacted_prompt

    def test_large_message_fails_closed(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        # Create a message larger than MAX_DLP_INPUT_SIZE
        text = "x" * (11 * 1024 * 1024)  # 11 MB
        with pytest.raises(DLPViolationError, match="inspection limit"):
            engine.inspect_message(text)

    def test_multiple_patterns(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"email": "test@test.com", "key": "api-abcdef1234567890abcdef"}'
        result = engine.inspect_message(text)
        assert "[REDACTED_EMAIL]" in result
        assert "[REDACTED_API_KEY]" in result

    def test_dlp_does_not_corrupt_unrelated_content(self, sample_config: GatewayConfig) -> None:
        engine = DLPEngine(sample_config)
        text = '{"status": "ok", "count": 42, "items": [1, 2, 3]}'
        result = engine.inspect_message(text)
        assert result == text

    def test_invalid_pattern_skipped(self, sample_config: GatewayConfig) -> None:
        sample_config.security.dlp_patterns = [
            DLPPattern(name="bad", pattern="[invalid", mode=DLPMode.REDACT, replacement="X"),
        ]
        # Should not raise, just skip the bad pattern
        engine = DLPEngine(sample_config)
        result = engine.inspect_message("test text")
        assert result == "test text"
