"""Atomic, in-process policy replacement and bounded version history."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import jsonschema

from mcp_guard.core.exceptions import ConfigurationError
from mcp_guard.core.models import GatewayConfig, PolicyAction, PolicyConfig
from mcp_guard.policies.engine import PolicyEngine

MAX_POLICY_VERSIONS = 100


class RuntimePolicyManager:
    """Validate full policy snapshots before atomically activating them."""

    def __init__(self, config: GatewayConfig, engine: PolicyEngine) -> None:
        self.config = config
        self.engine = engine
        self._lock = threading.RLock()
        self._version = 1
        self._history: dict[int, dict[str, Any]] = {
            1: {
                "policy": config.policy.model_copy(deep=True),
                "created_at": datetime.now(UTC).isoformat(),
                "action": "initial",
                "actor": "configuration",
            }
        }

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> tuple[int, PolicyConfig]:
        """Return the active version and a detached copy of its policy."""
        with self._lock:
            return self._version, self.engine.policy.model_copy(deep=True)

    def history(self) -> list[dict[str, Any]]:
        """Return version metadata without copying policy content into the log."""
        with self._lock:
            return [
                {
                    "version": version,
                    "created_at": item["created_at"],
                    "action": item["action"],
                    "actor": item["actor"],
                }
                for version, item in sorted(self._history.items())
            ]

    def update(self, policy: PolicyConfig, actor: str) -> int:
        """Validate and activate a new policy snapshot as one reference swap."""
        self._validate(policy)
        with self._lock:
            self.engine.policy = policy.model_copy(deep=True)
            self.engine.default_action = policy.default_action
            self.config.policy = self.engine.policy
            self._version += 1
            self._history[self._version] = {
                "policy": self.engine.policy.model_copy(deep=True),
                "created_at": datetime.now(UTC).isoformat(),
                "action": "update",
                "actor": actor,
            }
            self._trim_history()
            return self._version

    def rollback(self, version: int, actor: str) -> int:
        """Activate a historical policy as a new version, preserving history."""
        with self._lock:
            record = self._history.get(version)
            if record is None:
                raise ConfigurationError(f"Policy version {version} is not available")
            policy = record["policy"].model_copy(deep=True)
        self._validate(policy)
        with self._lock:
            self.engine.policy = policy
            self.engine.default_action = policy.default_action
            self.config.policy = policy
            self._version += 1
            self._history[self._version] = {
                "policy": policy.model_copy(deep=True),
                "created_at": datetime.now(UTC).isoformat(),
                "action": f"rollback:{version}",
                "actor": actor,
            }
            self._trim_history()
            return self._version

    def _validate(self, policy: PolicyConfig) -> None:
        if policy.default_action != PolicyAction.DENY:
            raise ConfigurationError("Runtime policy default_action must remain 'deny'")
        identity_ids = {agent.id for agent in self.config.identity.agents.values()}
        for agent_id, agent_policy in policy.agents.items():
            if agent_id not in identity_ids:
                raise ConfigurationError(f"Policy references unknown agent '{agent_id}'")
            identity = next(
                (agent for agent in self.config.identity.agents.values() if agent.id == agent_id),
                None,
            )
            for server_name, server in agent_policy.servers.items():
                if identity and identity.servers and server_name not in identity.servers:
                    raise ConfigurationError(
                        f"Policy server '{server_name}' is not assigned to agent '{agent_id}'"
                    )
                for kind, items in (
                    ("tool", server.tools),
                    ("resource", server.resources),
                    ("prompt", server.prompts),
                ):
                    for item_name, item_policy in items.items():
                        if not item_name.strip():
                            raise ConfigurationError(
                                f"Policy for '{agent_id}/{server_name}' contains an empty {kind}"
                            )
                        if kind != "tool" and item_policy.action == PolicyAction.APPROVAL_REQUIRED:
                            raise ConfigurationError(
                                "Approval-required policy is currently supported only for tools"
                            )
                        if kind == "resource" and item_policy.identity_argument_bindings:
                            raise ConfigurationError(
                                "Resource policies cannot use identity argument bindings"
                            )
                        if any(
                            not argument_name.strip()
                            or identity_field not in {"agent_id", "tenant_id", "user_id"}
                            for argument_name, identity_field in item_policy.identity_argument_bindings.items()
                        ):
                            raise ConfigurationError(
                                "Policy has an invalid identity argument binding"
                            )
                        constraint = item_policy.argument_constraints
                        if constraint and constraint.json_schema:
                            try:
                                jsonschema.Draft202012Validator.check_schema(constraint.json_schema)
                            except jsonschema.SchemaError as exc:
                                raise ConfigurationError(
                                    f"Invalid schema for {kind} '{item_name}': {exc.message}"
                                ) from exc
                        if (
                            constraint
                            and constraint.json_schema.get("additionalProperties") is False
                            and any(
                                argument_name not in constraint.json_schema.get("properties", {})
                                for argument_name in item_policy.identity_argument_bindings
                            )
                        ):
                            raise ConfigurationError(
                                "An identity-bound argument is excluded by its JSON Schema"
                            )
                if any(not method.strip() for method in server.methods):
                    raise ConfigurationError(
                        f"Policy for '{agent_id}/{server_name}' contains an empty method name"
                    )
                if any(
                    action == PolicyAction.APPROVAL_REQUIRED for action in server.methods.values()
                ):
                    raise ConfigurationError(
                        "Approval-required policy is currently supported only for tools"
                    )

    def _trim_history(self) -> None:
        while len(self._history) > MAX_POLICY_VERSIONS:
            oldest = min(self._history)
            if oldest == self._version:
                break
            self._history.pop(oldest)
