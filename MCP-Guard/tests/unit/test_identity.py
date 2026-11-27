"""Unit tests for the identity manager."""

from __future__ import annotations

import builtins
import hashlib

import pytest

from mcp_guard.core.exceptions import AuthenticationError
from mcp_guard.core.models import GatewayConfig, JWTAuthConfig
from mcp_guard.identity.manager import IdentityManager


class TestIdentityManager:
    def test_stdio_agent_identity(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        agent = mgr.verify_stdio_agent()
        assert agent.id == "support-agent-01"
        assert agent.enabled is True

    def test_missing_stdio_identity(self, sample_config: GatewayConfig) -> None:
        sample_config.identity.agent_id = ""
        mgr = IdentityManager(sample_config)
        with pytest.raises(AuthenticationError):
            mgr.verify_stdio_agent()

    def test_http_valid_token(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        token = "test-secret-token-12345"
        mgr.register_token("support-agent-01", token)
        agent = mgr.verify_http_agent(token)
        assert agent.id == "support-agent-01"

    def test_http_invalid_token(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        with pytest.raises(AuthenticationError):
            mgr.verify_http_agent("bad-token")

    def test_http_empty_token(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        with pytest.raises(AuthenticationError):
            mgr.verify_http_agent("")

    def test_disabled_agent_denied(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        token = "disabled-token"
        mgr.register_token("disabled-agent-01", token)
        with pytest.raises(AuthenticationError):
            mgr.verify_http_agent(token)

    def test_unknown_agent_denied(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        with pytest.raises(AuthenticationError):
            mgr._get_verified_agent("does-not-exist")

    def test_server_assignment(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        assert mgr.is_agent_assigned_to_server("support-agent-01", "customer_database") is True
        assert mgr.is_agent_assigned_to_server("support-agent-01", "analytics_database") is False

    def test_cannot_spoof_identity(self, sample_config: GatewayConfig) -> None:
        """Agent cannot spoof another agent's identity via token."""
        mgr = IdentityManager(sample_config)
        token = "support-token"
        mgr.register_token("support-agent-01", token)
        # Using the support agent's token should return support-agent-01, not admin
        agent = mgr.verify_http_agent(token)
        assert agent.id == "support-agent-01"
        assert agent.id != "admin-agent-01"

    def test_token_rotation_and_revocation_fail_closed(self, sample_config: GatewayConfig) -> None:
        mgr = IdentityManager(sample_config)
        old_token = "old-high-entropy-token"
        new_token = "new-high-entropy-token"
        mgr.register_token("support-agent-01", old_token)
        mgr.rotate_token_hash(
            hashlib.sha256(old_token.encode()).hexdigest(),
            hashlib.sha256(new_token.encode()).hexdigest(),
        )
        with pytest.raises(AuthenticationError):
            mgr.verify_http_context(old_token)
        assert mgr.verify_http_context(new_token).agent_id == "support-agent-01"
        mgr.revoke_token_hash(hashlib.sha256(new_token.encode()).hexdigest())
        with pytest.raises(AuthenticationError):
            mgr.verify_http_context(new_token)

    def test_jwt_mode_fails_closed_when_optional_validator_is_missing(
        self, sample_config: GatewayConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sample_config.identity.jwt = JWTAuthConfig(
            enabled=True,
            issuer="https://identity.example",
            audience="mcp-guard",
            algorithms=["HS256"],
        )
        mgr = IdentityManager(sample_config)
        original_import = builtins.__import__

        def import_without_jwt(name, *args, **kwargs):
            if name == "jwt":
                raise ModuleNotFoundError("JWT extra is intentionally unavailable in this test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_without_jwt)
        with pytest.raises(AuthenticationError):
            mgr.verify_http_context("unsigned.jwt.token")
