"""Configuration loading and validation for MCP-Guard."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import jsonschema
import yaml
from pydantic import ValidationError

from mcp_guard.core.constants import (
    REDACTED_API_KEY,
    REDACTED_EMAIL,
    REDACTED_PHONE,
    REDACTED_TOKEN,
)
from mcp_guard.core.exceptions import ConfigurationError
from mcp_guard.core.models import (
    DLPMode,
    DLPPattern,
    GatewayConfig,
    PolicyAction,
)
from mcp_guard.security.dlp import (
    MAX_DLP_INPUT_SIZE,
    PYTHON_REQUIRES_TIMEOUT_REGEX,
    is_safe_pattern,
)


def _default_dlp_patterns() -> list[DLPPattern]:
    """Return safe default DLP patterns."""
    return [
        DLPPattern(
            name="email",
            pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            mode=DLPMode.REDACT,
            replacement=REDACTED_EMAIL,
        ),
        DLPPattern(
            name="phone_us",
            pattern=r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            mode=DLPMode.REDACT,
            replacement=REDACTED_PHONE,
        ),
        DLPPattern(
            name="api_key",
            pattern=r"\b(?:sk|pk|api|key|token)[-_][a-zA-Z0-9]{20,}\b",
            mode=DLPMode.REDACT,
            replacement=REDACTED_API_KEY,
        ),
        DLPPattern(
            name="bearer_token",
            pattern=r"Bearer\s+[a-zA-Z0-9._~+/=-]{20,}",
            mode=DLPMode.REDACT,
            replacement=REDACTED_TOKEN,
        ),
    ]


def _resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} references in string values."""
    if not isinstance(value, str):
        return value

    def replace_env(match: Any) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ConfigurationError(f"Environment variable '{var_name}' is not set")
        return os.environ[var_name]

    return re.sub(r"\$\{([^}]+)\}", replace_env, value)


def _resolve_env_in_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve environment variables in a dictionary."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _resolve_env_vars(v)
        elif isinstance(v, dict):
            result[k] = _resolve_env_in_dict(v)
        elif isinstance(v, list):
            result[k] = [
                _resolve_env_in_dict(i)
                if isinstance(i, dict)
                else (_resolve_env_vars(i) if isinstance(i, str) else i)
                for i in v
            ]
        else:
            result[k] = v
    return result


def hash_api_key(api_key: str) -> str:
    """Hash an API key for safe storage using SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def load_yaml_file(path: str) -> dict[str, Any]:
    """Load and parse a YAML file."""
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")
    if not file_path.is_file():
        raise ConfigurationError(f"Configuration path is not a file: {path}")

    class UniqueKeyLoader(yaml.SafeLoader):
        """YAML safe loader that rejects ambiguous duplicate keys."""

    def construct_mapping(
        loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        loader.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.YAMLError(f"Duplicate key '{key}' in configuration")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )

    try:
        with open(file_path, encoding="utf-8") as f:
            loader = UniqueKeyLoader(f)
            try:
                data = loader.get_single_data()
            finally:
                loader.dispose()
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise ConfigurationError(f"Configuration file must contain a YAML mapping: {path}")

    return data


def load_config(
    config_path: str,
    policy_path: Optional[str] = None,
    agents_path: Optional[str] = None,
) -> GatewayConfig:
    """Load and validate the full gateway configuration.

    Args:
        config_path: Path to the main config YAML.
        policy_path: Optional separate policy YAML.
        agents_path: Optional separate agents YAML.

    Returns:
        Validated GatewayConfig.

    Raises:
        ConfigurationError on invalid configuration.
    """
    raw = load_yaml_file(config_path)
    raw = _resolve_env_in_dict(raw)

    # Extract from mcp_guard key if present
    if "mcp_guard" in raw:
        raw = raw["mcp_guard"]

    # Load separate policy file if provided
    if policy_path:
        policy_raw = load_yaml_file(policy_path)
        policy_raw = _resolve_env_in_dict(policy_raw)
        if "policy" in policy_raw:
            raw["policy"] = policy_raw["policy"]
        else:
            raw["policy"] = policy_raw

    # Load separate agents file if provided
    if agents_path:
        agents_raw = load_yaml_file(agents_path)
        agents_raw = _resolve_env_in_dict(agents_raw)
        if "identity" not in raw:
            raw["identity"] = {}
        if "agents" in agents_raw:
            raw["identity"]["agents"] = agents_raw["agents"]
        else:
            raw["identity"]["agents"] = agents_raw

    try:
        config = GatewayConfig(**raw)
    except ValidationError as e:
        raise ConfigurationError(f"Configuration validation failed:\n{e}") from e

    # Apply default DLP patterns if none configured
    if config.security.enable_dlp and not config.security.dlp_patterns:
        config.security.dlp_patterns = _default_dlp_patterns()

    return config


def validate_config(config: GatewayConfig) -> tuple[bool, list[str]]:
    """Validate a loaded configuration for completeness and consistency.

    Returns:
        Tuple of (is_valid, list_of_issues).
    """
    issues: list[str] = []

    # The product is explicitly default-deny; accepting an allow default would
    # make absent per-tool rules effective permissions.
    if config.default_policy != PolicyAction.DENY:
        issues.append("The top-level default_policy must be 'deny'.")
    if config.policy.default_action != PolicyAction.DENY:
        issues.append("policy.default_action must be 'deny'; add explicit allow rules per tool.")

    # Check transport config
    if config.transport == "stdio":
        if not config.stdio:
            issues.append("STDIO transport selected but no 'stdio' configuration provided.")
        else:
            if not config.stdio.upstream.command:
                issues.append("STDIO upstream must have a 'command' configured.")
            if not config.stdio.upstream.name.strip():
                issues.append("STDIO upstream must have a non-empty name.")
        if not config.identity.agent_id:
            issues.append("STDIO transport requires identity.agent_id.")
        elif not any(
            agent.id == config.identity.agent_id for agent in config.identity.agents.values()
        ):
            issues.append(
                f"STDIO identity '{config.identity.agent_id}' is not configured in identity.agents."
            )
    elif config.transport == "http":
        if not config.http:
            issues.append("HTTP transport selected but no 'http' configuration provided.")
        elif not _is_http_url(config.http.upstream_url):
            issues.append("HTTP transport requires a valid http(s) upstream_url.")
        if not config.identity.agents:
            issues.append("HTTP transport requires at least one configured agent.")
        elif not (
            any(agent.api_key_hash for agent in config.identity.agents.values())
            or config.identity.credentials
            or (config.identity.jwt and config.identity.jwt.enabled)
        ):
            issues.append(
                "HTTP transport requires at least one agent with api_key_hash configured."
            )
    else:
        issues.append(f"Unknown transport type: {config.transport}")

    # Check policy
    if not config.policy.agents:
        issues.append("WARNING: No agent policies configured. Tool calls will be denied.")

    # Check identity
    if not config.identity.agents and config.transport == "http":
        issues.append("WARNING: No agents configured for identity. HTTP auth will reject all.")

    # Validate DLP patterns compile
    if config.security.enable_dlp:
        if PYTHON_REQUIRES_TIMEOUT_REGEX:
            try:
                import regex  # noqa: F401
            except ImportError:
                issues.append(
                    "The regex dependency is required on Python 3.11+ for bounded DLP matching."
                )
        if config.security.max_message_size > MAX_DLP_INPUT_SIZE:
            issues.append(
                "security.max_message_size must not exceed the DLP inspection limit when DLP is enabled."
            )
        for pat in config.security.dlp_patterns:
            try:
                re.compile(pat.pattern)
            except re.error as e:
                issues.append(f"Invalid DLP regex pattern '{pat.name}': {e}")
                continue
            if not is_safe_pattern(pat.pattern):
                issues.append(
                    f"DLP regex pattern '{pat.name}' is too complex or exceeds the safe limit."
                )
            if any(
                not value.strip()
                for values in (
                    pat.agents,
                    pat.tenant_ids,
                    pat.user_ids,
                    pat.servers,
                    pat.methods,
                    pat.directions,
                )
                for value in values
            ):
                issues.append(f"DLP pattern '{pat.name}' contains an empty scope value.")
            if any(direction not in {"request", "response"} for direction in pat.directions):
                issues.append(
                    f"DLP pattern '{pat.name}' directions must be 'request' or 'response'."
                )

        configured_agents = {agent.id for agent in config.identity.agents.values()}
        configured_servers = set(config.upstreams)
        configured_servers.update(
            server_name
            for agent in config.identity.agents.values()
            for server_name in agent.servers
        )
        configured_servers.update(
            server_name
            for agent_policy in config.policy.agents.values()
            for server_name in agent_policy.servers
        )
        if config.http:
            configured_servers.add("http_upstream")
            configured_servers.update(
                route.server_name for route in config.http.rest_actions.values()
            )
        if config.stdio:
            configured_servers.add(config.stdio.upstream.name)
        for pat in config.security.dlp_patterns:
            if any(agent_id not in configured_agents for agent_id in pat.agents):
                issues.append(f"DLP pattern '{pat.name}' references an unknown agent.")
            if any(server_name not in configured_servers for server_name in pat.servers):
                issues.append(f"DLP pattern '{pat.name}' references an unknown server.")

    if config.logging.format != "jsonl":
        issues.append("logging.format must be 'jsonl'.")
    if config.logging.level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        issues.append("logging.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    if not config.logging.file.strip():
        issues.append("logging.file must not be empty.")

    # Validate identities and credentials before creating transport clients.
    agent_ids = [agent.id for agent in config.identity.agents.values()]
    identity_ids = set(agent_ids)
    if len(agent_ids) != len(set(agent_ids)):
        issues.append("Agent IDs in identity.agents must be unique.")
    token_hashes: list[str] = []
    for key, agent in config.identity.agents.items():
        if not key.strip() or not agent.id.strip():
            issues.append("Identity keys and agent IDs must be non-empty strings.")
        if not agent.servers:
            issues.append(f"Agent '{agent.id}' must have at least one assigned server.")
        if agent.api_key_hash:
            digest = agent.api_key_hash.removeprefix("sha256:")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                issues.append(f"Agent '{agent.id}' api_key_hash must be a SHA-256 hex digest.")
            token_hashes.append(digest.lower())
    for credential_name, credential in config.identity.credentials.items():
        if not credential_name.strip():
            issues.append("Identity credential keys must be non-empty strings.")
        if credential.agent_id not in identity_ids:
            issues.append(
                f"Identity credential '{credential_name}' references unknown agent '{credential.agent_id}'."
            )
        digest = credential.api_key_hash.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            issues.append(
                f"Identity credential '{credential_name}' api_key_hash must be a SHA-256 hex digest."
            )
        else:
            token_hashes.append(digest.lower())
    for credential_name, admin_credential in config.identity.admin_credentials.items():
        if not credential_name.strip() or not admin_credential.id.strip():
            issues.append("Administrator credential keys and IDs must be non-empty strings.")
        digest = admin_credential.api_key_hash.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            issues.append(
                f"Administrator credential '{credential_name}' api_key_hash must be a SHA-256 hex digest."
            )
        else:
            token_hashes.append(digest.lower())
        if admin_credential.enabled and "admin" not in admin_credential.roles:
            issues.append(
                f"Enabled administrator credential '{credential_name}' must include the 'admin' role."
            )
    if len(token_hashes) != len(set(token_hashes)):
        issues.append("Each HTTP agent must have a unique api_key_hash.")

    configured_servers = set(config.upstreams)
    configured_servers.update(
        server_name for agent in config.identity.agents.values() for server_name in agent.servers
    )
    if config.stdio and config.stdio.upstream:
        configured_servers.add(config.stdio.upstream.name)
    if config.http and config.http.upstream_url:
        matched = [
            name
            for name, upstream in config.upstreams.items()
            if upstream.url == config.http.upstream_url
        ]
        configured_servers.update(matched or ["http_upstream"])
    if config.http:
        configured_servers.update(route.server_name for route in config.http.rest_actions.values())
        for action, route in config.http.rest_actions.items():
            if not action.strip():
                issues.append("HTTP REST action names must not be empty.")
            if not route.server_name.strip():
                issues.append(f"REST action '{action}' must have a non-empty server_name.")
            if not _is_http_url(route.url):
                issues.append(f"REST action '{action}' must use a valid http(s) URL.")
            if route.method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                issues.append(
                    f"REST action '{action}' method must be GET, POST, PUT, PATCH, or DELETE."
                )
            for header_name, header_value in route.upstream_headers.items():
                if (
                    not header_name.strip()
                    or "\r" in header_name
                    or "\n" in header_name
                    or "\r" in header_value
                    or "\n" in header_value
                    or header_name.lower()
                    in {
                        "host",
                        "content-length",
                        "connection",
                        "transfer-encoding",
                        "content-type",
                        "accept",
                    }
                ):
                    issues.append(f"REST action '{action}' contains an invalid upstream header.")

    # Validate policy references and every configured JSON Schema at startup.
    for agent_id, agent_policy in config.policy.agents.items():
        if agent_id not in identity_ids:
            issues.append(f"Policy references unknown agent '{agent_id}'.")
        for server_name in agent_policy.servers:
            if (
                config.transport == "http"
                and configured_servers
                and server_name not in configured_servers
            ):
                issues.append(f"Policy for '{agent_id}' references unknown server '{server_name}'.")
            identity = next(
                (item for item in config.identity.agents.values() if item.id == agent_id), None
            )
            if identity and identity.servers and server_name not in identity.servers:
                issues.append(
                    f"Policy server '{server_name}' is not assigned to agent '{agent_id}'."
                )
            server_policy = agent_policy.servers[server_name]
            for kind, items in (
                ("tool", server_policy.tools),
                ("resource", server_policy.resources),
                ("prompt", server_policy.prompts),
            ):
                for item_name, item_policy in items.items():
                    if not item_name.strip():
                        issues.append(
                            f"Policy for '{agent_id}' contains an empty {kind} name or URI."
                        )
                    if kind != "tool" and item_policy.action == PolicyAction.APPROVAL_REQUIRED:
                        issues.append(
                            f"Approval-required policy is currently supported only for tools; "
                            f"'{kind}' '{agent_id}/{server_name}/{item_name}' must use allow or deny."
                        )
                    if kind == "resource" and item_policy.identity_argument_bindings:
                        issues.append(
                            f"Resource policy '{agent_id}/{server_name}/{item_name}' cannot use argument bindings."
                        )
                    for (
                        argument_name,
                        identity_field,
                    ) in item_policy.identity_argument_bindings.items():
                        if not argument_name.strip() or identity_field not in {
                            "agent_id",
                            "tenant_id",
                            "user_id",
                        }:
                            issues.append(
                                f"Policy '{agent_id}/{server_name}/{item_name}' has an invalid identity argument binding."
                            )
                        constraint = item_policy.argument_constraints
                        if (
                            constraint
                            and constraint.json_schema.get("additionalProperties") is False
                            and argument_name not in constraint.json_schema.get("properties", {})
                        ):
                            issues.append(
                                f"Identity-bound argument '{argument_name}' is excluded by the JSON Schema for '{item_name}'."
                            )
                    constraint = item_policy.argument_constraints
                    if constraint and constraint.json_schema:
                        try:
                            jsonschema.Draft202012Validator.check_schema(constraint.json_schema)
                        except jsonschema.SchemaError as e:
                            issues.append(
                                f"Invalid {kind} schema for '{agent_id}/{server_name}/{item_name}': {e.message}"
                            )
            if any(not method.strip() for method in server_policy.methods):
                issues.append(f"Policy for '{agent_id}/{server_name}' contains an empty method.")
            if any(
                action == PolicyAction.APPROVAL_REQUIRED
                for action in server_policy.methods.values()
            ):
                issues.append(
                    f"Approval-required policy is currently supported only for tools; "
                    f"methods under '{agent_id}/{server_name}' must use allow or deny."
                )

    if config.transport == "stdio" and config.stdio:
        if config.stdio.upstream.name not in configured_servers:
            issues.append("STDIO upstream name is not configured.")
    if config.http:
        if "*" in config.http.allowed_origins:
            issues.append("HTTP allowed_origins must list exact origins; '*' is not supported.")
        for header_name, header_value in config.http.upstream_headers.items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header_name):
                issues.append(f"Invalid configured upstream HTTP header name: '{header_name}'.")
            if header_name.lower() in {
                "host",
                "content-length",
                "content-type",
                "accept",
                "connection",
                "transfer-encoding",
                "proxy-authorization",
                "cookie",
                "origin",
                "mcp-protocol-version",
                "mcp-method",
                "mcp-name",
                "mcp-session-id",
            } or header_name.lower().startswith("mcp-param-"):
                issues.append(f"Configured upstream HTTP header '{header_name}' is reserved.")
            if any(ord(char) < 32 or ord(char) == 127 for char in header_value):
                issues.append(
                    f"Configured upstream HTTP header '{header_name}' contains control characters."
                )
        if bool(config.http.tls_cert_file) != bool(config.http.tls_key_file):
            issues.append("HTTP TLS requires both tls_cert_file and tls_key_file.")
        if config.http.require_client_certificate and not config.http.client_ca_file:
            issues.append("HTTP client certificate validation requires client_ca_file.")
        if config.http.client_ca_file and not config.http.tls_cert_file:
            issues.append("HTTP client_ca_file requires the gateway TLS certificate and key.")

    jwt_config = config.identity.jwt
    if jwt_config and jwt_config.enabled:
        if not jwt_config.issuer.strip() or not jwt_config.audience.strip():
            issues.append("Enabled JWT authentication requires issuer and audience.")
        if not jwt_config.algorithms or any(
            algorithm == "none"
            or algorithm
            not in {
                "RS256",
                "RS384",
                "RS512",
                "ES256",
                "ES384",
                "EdDSA",
                "HS256",
                "HS384",
                "HS512",
            }
            for algorithm in jwt_config.algorithms
        ):
            issues.append("JWT algorithms must be an explicit supported signed algorithm list.")
        key_sources = sum(
            bool(value)
            for value in (jwt_config.jwks_url, jwt_config.public_keys, jwt_config.secret)
        )
        if key_sources != 1:
            issues.append(
                "JWT authentication requires exactly one of jwks_url, public_keys, or secret."
            )
        if jwt_config.jwks_url and not jwt_config.jwks_url.startswith("https://"):
            issues.append("JWT jwks_url must use HTTPS.")
        if jwt_config.secret and any(not alg.startswith("HS") for alg in jwt_config.algorithms):
            issues.append("JWT secret keys may only be used with HS256/HS384/HS512.")
        if (jwt_config.public_keys or jwt_config.jwks_url) and any(
            alg.startswith("HS") for alg in jwt_config.algorithms
        ):
            issues.append("JWT public/JWKS keys may not be combined with HMAC algorithms.")
        if any(not scope.strip() for scope in jwt_config.required_scopes):
            issues.append("JWT required_scopes may not contain empty values.")

    is_valid = not any(not issue.startswith("WARNING:") for issue in issues)
    return is_valid, issues


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return port is None or 1 <= port <= 65535
