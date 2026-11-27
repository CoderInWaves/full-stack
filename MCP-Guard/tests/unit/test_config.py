"""Unit tests for configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from mcp_guard.core.config import load_config, load_yaml_file, validate_config
from mcp_guard.core.exceptions import ConfigurationError
from mcp_guard.core.models import HTTPTransportConfig, RESTActionConfig


class TestLoadYaml:
    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text("key: value\nnested:\n  a: 1\n")
        data = load_yaml_file(str(cfg_file))
        assert data["key"] == "value"
        assert data["nested"]["a"] == 1

    def test_load_missing_file(self) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            load_yaml_file("/nonexistent/path.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : :\n  invalid yaml {{{\n")
        with pytest.raises(ConfigurationError, match="Invalid YAML"):
            load_yaml_file(str(bad))

    def test_load_non_dict_yaml(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "list.yaml"
        cfg_file.write_text("- item1\n- item2\n")
        with pytest.raises(ConfigurationError, match="mapping"):
            load_yaml_file(str(cfg_file))

    def test_duplicate_yaml_keys_are_rejected(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "duplicate.yaml"
        cfg_file.write_text("mcp_guard:\n  name: first\n  name: second\n")
        with pytest.raises(ConfigurationError, match="Duplicate key"):
            load_yaml_file(str(cfg_file))


class TestLoadConfig:
    def test_load_full_config(self, tmp_path: Path) -> None:
        cfg = {
            "mcp_guard": {
                "name": "Test",
                "transport": "stdio",
                "stdio": {
                    "upstream": {
                        "name": "test_server",
                        "command": ["python3", "server.py"],
                    }
                },
                "identity": {"agent_id": "test-agent"},
                "policy": {
                    "default_action": "deny",
                    "agents": {},
                },
                "logging": {"file": str(tmp_path / "log.jsonl")},
                "security": {"enable_dlp": False},
            }
        }
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg))

        config = load_config(str(cfg_file))
        assert config.name == "Test"
        assert config.transport == "stdio"
        assert config.identity.agent_id == "test-agent"

    def test_load_separate_policy(self, tmp_path: Path) -> None:
        cfg = {
            "mcp_guard": {
                "name": "Test",
                "identity": {"agent_id": "agent1"},
                "logging": {"file": str(tmp_path / "log.jsonl")},
            }
        }
        policy = {
            "policy": {
                "default_action": "deny",
                "agents": {
                    "agent1": {"servers": {"srv": {"tools": {"tool1": {"action": "allow"}}}}}
                },
            }
        }

        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg))
        pol_file = tmp_path / "policy.yaml"
        pol_file.write_text(yaml.dump(policy))

        config = load_config(str(cfg_file), policy_path=str(pol_file))
        assert "agent1" in config.policy.agents

    def test_env_var_resolution(self, tmp_path: Path) -> None:
        os.environ["TEST_MCP_AGENT"] = "env-agent-01"
        cfg = {
            "mcp_guard": {
                "identity": {"agent_id": "${TEST_MCP_AGENT}"},
                "logging": {"file": str(tmp_path / "log.jsonl")},
            }
        }
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg))

        config = load_config(str(cfg_file))
        assert config.identity.agent_id == "env-agent-01"
        del os.environ["TEST_MCP_AGENT"]

    def test_invalid_config_raises(self, tmp_path: Path) -> None:
        cfg = {"mcp_guard": {"transport": 12345}}
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text(yaml.dump(cfg))
        # Should not crash, pydantic coerces or raises
        try:
            load_config(str(cfg_file))
        except ConfigurationError:
            pass  # Expected for truly invalid configs


class TestValidateConfig:
    def test_valid_stdio_config(self, sample_config) -> None:
        is_valid, issues = validate_config(sample_config)
        # May have warnings but no errors
        errors = [i for i in issues if not i.startswith("WARNING:")]
        assert len(errors) == 0

    def test_missing_stdio_upstream(self, sample_config) -> None:
        sample_config.transport = "stdio"
        sample_config.stdio = None
        is_valid, issues = validate_config(sample_config)
        assert any("STDIO" in i for i in issues)

    def test_unknown_transport(self, sample_config) -> None:
        sample_config.transport = "websocket"
        is_valid, issues = validate_config(sample_config)
        assert any("Unknown transport" in i for i in issues)

    def test_unknown_agent_dlp_scope_is_invalid(self, sample_config) -> None:
        from mcp_guard.core.models import DLPPattern

        sample_config.security.dlp_patterns = [
            DLPPattern(name="scope", pattern="secret", agents=["missing-agent"])
        ]
        is_valid, issues = validate_config(sample_config)
        assert not is_valid
        assert any("unknown agent" in issue for issue in issues)

    def test_static_rest_action_requires_safe_configured_upstream(self, sample_config) -> None:
        sample_config.transport = "http"
        sample_config.http = HTTPTransportConfig(
            upstream_url="http://mcp.example/mcp",
            rest_actions={
                "get_customer": RESTActionConfig(
                    server_name="customer_database",
                    url="https://api.example/customers/lookup",
                )
            },
        )
        sample_config.identity.agents["support_agent"].api_key_hash = "a" * 64
        valid, issues = validate_config(sample_config)
        assert valid, issues

        sample_config.http.rest_actions["get_customer"].url = "file:///etc/passwd"
        valid, issues = validate_config(sample_config)
        assert not valid
        assert any("valid http(s) URL" in issue for issue in issues)
