"""Deterministic policy engine for MCP tools, resources, prompts, and methods."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import jsonschema

from mcp_guard.core.constants import (
    DECISION_ALLOW,
    DECISION_APPROVAL_REQUIRED,
    DECISION_DENY,
    REASON_APPROVAL_REQUIRED,
    REASON_DEFAULT_DENY,
    REASON_DISABLED_AGENT,
    REASON_INVALID_ARGUMENTS,
    REASON_MISSING_IDENTITY,
    REASON_SERVER_DISABLED,
    REASON_SERVER_NOT_ASSIGNED,
    REASON_TOOL_DENIED,
    REASON_UNKNOWN_AGENT,
)
from mcp_guard.core.models import (
    AgentIdentity,
    AgentPolicy,
    GatewayConfig,
    IdentityContext,
    PolicyAction,
    SecurityDecision,
    ServerPolicy,
    ToolCallInfo,
    ToolPolicy,
)

logger = logging.getLogger("mcp_guard.policy")


class PolicyEngine:
    """Evaluate trusted identities against explicit, default-deny policies."""

    def __init__(self, config: GatewayConfig) -> None:
        self.policy = config.policy
        self.default_action = config.policy.default_action
        self._identity_agents = config.identity.agents

    def evaluate(
        self, tool_call: ToolCallInfo, approval_accepted: bool = False
    ) -> SecurityDecision:
        """Evaluate a tool invocation, including tenant and user scopes."""
        context = tool_call.identity_context or self._context_for_agent(
            tool_call.agent_id,
            tool_call.tenant_id,
            tool_call.user_id,
            tool_call.roles,
        )
        context, server_policy, denial = self._base_check(
            tool_call.agent_id, tool_call.server_name, context, tool_call.tool_name
        )
        if denial:
            return denial
        assert server_policy is not None

        tool_policy = server_policy.tools.get(tool_call.tool_name)
        if tool_policy is None:
            return self._denial(
                "TOOL_NOT_ALLOWED",
                "No policy for tool",
                context,
                tool_call.server_name,
                tool_call.tool_name,
            )
        if tool_policy.action == PolicyAction.DENY:
            return self._denial(
                REASON_TOOL_DENIED,
                "Tool is explicitly denied",
                context,
                tool_call.server_name,
                tool_call.tool_name,
            )
        if not self._scope_allows(tool_policy, context):
            return self._denial(
                "IDENTITY_SCOPE_DENIED",
                "Identity context does not match the configured tool scope",
                context,
                tool_call.server_name,
                tool_call.tool_name,
            )

        constraint = tool_policy.argument_constraints
        if constraint and constraint.json_schema:
            valid, error = self._validate_arguments(tool_call.arguments, constraint.json_schema)
            if not valid:
                return self._denial(
                    REASON_INVALID_ARGUMENTS,
                    f"Invalid arguments for tool: {error}",
                    context,
                    tool_call.server_name,
                    tool_call.tool_name,
                )

        if not self._identity_arguments_match(
            tool_policy.identity_argument_bindings, tool_call.arguments, context
        ):
            return self._denial(
                "IDENTITY_ARGUMENT_MISMATCH",
                "Tool arguments do not match the trusted identity context",
                context,
                tool_call.server_name,
                tool_call.tool_name,
            )

        if tool_policy.action == PolicyAction.APPROVAL_REQUIRED and not approval_accepted:
            return SecurityDecision(
                allowed=False,
                decision=DECISION_APPROVAL_REQUIRED,
                reason_code=REASON_APPROVAL_REQUIRED,
                reason_message="Tool requires approval",
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server_name=tool_call.server_name,
                tool_name=tool_call.tool_name,
            )

        return SecurityDecision(
            allowed=True,
            decision=DECISION_ALLOW,
            reason_code=("APPROVAL_GRANTED" if approval_accepted else ""),
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            server_name=tool_call.server_name,
            tool_name=tool_call.tool_name,
        )

    def evaluate_resource(
        self,
        agent_id: str,
        server_name: str,
        uri: str,
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize an exact resource URI, including direct URI construction."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id), uri
        )
        if denial:
            return denial
        assert server_policy is not None

        matches = [
            rule
            for uri_template, rule in server_policy.resources.items()
            if self._render_uri_template(uri_template, context) == uri
        ]
        return self._evaluate_named_rules(
            matches,
            context,
            server_name,
            uri,
            kind="resource",
        )

    def evaluate_prompt(
        self,
        agent_id: str,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, Any],
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize prompt retrieval and validate its arguments."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id), prompt_name
        )
        if denial:
            return denial
        assert server_policy is not None
        rule = server_policy.prompts.get(prompt_name)
        if rule is None:
            return self._denial(
                "PROMPT_NOT_ALLOWED",
                "No policy for prompt",
                context,
                server_name,
                prompt_name,
            )
        decision = self._evaluate_named_rules([rule], context, server_name, prompt_name, "prompt")
        if not decision.allowed:
            return decision
        constraint = rule.argument_constraints
        if constraint and constraint.json_schema:
            valid, error = self._validate_arguments(arguments, constraint.json_schema)
            if not valid:
                return self._denial(
                    REASON_INVALID_ARGUMENTS,
                    f"Invalid prompt arguments: {error}",
                    context,
                    server_name,
                    prompt_name,
                )
        if not self._identity_arguments_match(rule.identity_argument_bindings, arguments, context):
            return self._denial(
                "IDENTITY_ARGUMENT_MISMATCH",
                "Prompt arguments do not match the trusted identity context",
                context,
                server_name,
                prompt_name,
            )
        return decision

    def evaluate_method(
        self,
        agent_id: str,
        server_name: str,
        method: str,
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Evaluate a non-core operation through an explicit per-method rule."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id), method
        )
        if denial:
            return denial
        assert server_policy is not None
        action = server_policy.methods.get(method)
        if action is None or action == PolicyAction.DENY:
            return self._denial(
                "METHOD_NOT_ALLOWED",
                "No allow policy for this MCP method",
                context,
                server_name,
                method,
            )
        if action == PolicyAction.APPROVAL_REQUIRED:
            return SecurityDecision(
                allowed=False,
                decision=DECISION_APPROVAL_REQUIRED,
                reason_code=REASON_APPROVAL_REQUIRED,
                reason_message="MCP method requires approval",
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server_name=server_name,
                tool_name=method,
            )
        return SecurityDecision(
            allowed=True,
            decision=DECISION_ALLOW,
            reason_code="METHOD_ALLOWED",
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            server_name=server_name,
            tool_name=method,
        )

    def get_allowed_tools(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        """Return tools visible to the identity; calls are still checked again."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id)
        )
        if denial or server_policy is None:
            return []
        return [
            name
            for name, rule in server_policy.tools.items()
            if rule.action in (PolicyAction.ALLOW, PolicyAction.APPROVAL_REQUIRED)
            and self._scope_allows(rule, context)
        ]

    def get_allowed_prompts(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        """Return explicitly allowed prompt names for discovery filtering."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id)
        )
        if denial or server_policy is None:
            return []
        return [
            name
            for name, rule in server_policy.prompts.items()
            if rule.action == PolicyAction.ALLOW and self._scope_allows(rule, context)
        ]

    def get_allowed_resource_templates(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        """Return resource templates explicitly granted by policy."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id)
        )
        if denial or server_policy is None:
            return []
        return [
            template
            for template, rule in server_policy.resources.items()
            if rule.action == PolicyAction.ALLOW and self._scope_allows(rule, context)
        ]

    def get_allowed_servers(self, agent_id: str) -> list[str]:
        """Return servers explicitly assigned and enabled for this identity."""
        identity = self._find_identity(agent_id)
        agent_policy = self.policy.agents.get(agent_id)
        if identity is None or not identity.enabled or agent_policy is None:
            return []
        configured = set(agent_policy.servers)
        if identity.servers:
            configured.intersection_update(identity.servers)
        return sorted(name for name in configured if agent_policy.servers[name].enabled)

    def get_allowed_resources(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        """Return only resource URIs that are concrete for this identity."""
        context, server_policy, denial = self._base_check(
            agent_id, server_name, context or self._context_for_agent(agent_id)
        )
        if denial or server_policy is None:
            return []
        allowed: list[str] = []
        for uri_template, rule in server_policy.resources.items():
            if rule.action != PolicyAction.ALLOW or not self._scope_allows(rule, context):
                continue
            uri = self._render_uri_template(uri_template, context)
            if uri and uri not in allowed:
                allowed.append(uri)
        return allowed

    def _base_check(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext],
        item_name: str = "",
    ) -> tuple[IdentityContext, Optional[ServerPolicy], Optional[SecurityDecision]]:
        identity = self._find_identity(agent_id)
        if not agent_id:
            resolved = context or IdentityContext(agent_id="")
            return (
                resolved,
                None,
                self._denial(
                    REASON_MISSING_IDENTITY,
                    "No identity was established",
                    resolved,
                    server_name,
                    item_name,
                ),
            )
        if identity is None:
            resolved = context or IdentityContext(agent_id=agent_id)
            return (
                resolved,
                None,
                self._denial(
                    REASON_UNKNOWN_AGENT,
                    "Identity is not configured",
                    resolved,
                    server_name,
                    item_name,
                ),
            )

        resolved = context or self._context_for_agent(agent_id)
        if resolved.agent_id != agent_id:
            return (
                resolved,
                None,
                self._denial(
                    "IDENTITY_CONTEXT_MISMATCH",
                    "Verified identity context does not match the request agent",
                    resolved,
                    server_name,
                    item_name,
                ),
            )
        if not identity.enabled:
            return (
                resolved,
                None,
                self._denial(
                    REASON_DISABLED_AGENT, "Agent is disabled", resolved, server_name, item_name
                ),
            )
        if identity.servers and server_name not in identity.servers:
            return (
                resolved,
                None,
                self._denial(
                    REASON_SERVER_NOT_ASSIGNED,
                    "Agent is not assigned to this server",
                    resolved,
                    server_name,
                    item_name,
                ),
            )

        agent_policy = self.policy.agents.get(agent_id)
        if agent_policy is None:
            return (
                resolved,
                None,
                self._denial(
                    REASON_DEFAULT_DENY,
                    "No policy is configured for this agent",
                    resolved,
                    server_name,
                    item_name,
                ),
            )
        scope_denial = self._identity_scope_denial(identity, agent_policy, resolved, server_name)
        if scope_denial:
            return (
                resolved,
                None,
                self._denial(
                    scope_denial,
                    "Verified tenant, user, or role context is outside the policy scope",
                    resolved,
                    server_name,
                    item_name,
                ),
            )

        server_policy = agent_policy.servers.get(server_name)
        if server_policy is None:
            return (
                resolved,
                None,
                self._denial(
                    REASON_SERVER_NOT_ASSIGNED,
                    "No policy is configured for this server",
                    resolved,
                    server_name,
                    item_name,
                ),
            )
        if not server_policy.enabled:
            return (
                resolved,
                None,
                self._denial(
                    REASON_SERVER_DISABLED,
                    "Server is disabled by policy",
                    resolved,
                    server_name,
                    item_name,
                ),
            )
        return resolved, server_policy, None

    def _identity_scope_denial(
        self,
        identity: AgentIdentity,
        agent_policy: AgentPolicy,
        context: IdentityContext,
        server_name: str,
    ) -> str:
        allowed_tenants = set(identity.allowed_tenants)
        if identity.tenant_id:
            allowed_tenants.add(identity.tenant_id)
        if allowed_tenants and context.tenant_id not in allowed_tenants:
            return "TENANT_NOT_ALLOWED"
        allowed_users = set(identity.allowed_users)
        if identity.user_id:
            allowed_users.add(identity.user_id)
        if allowed_users and context.user_id not in allowed_users:
            return "USER_NOT_ALLOWED"
        if not self._scope_lists_allow(
            agent_policy.tenant_ids, agent_policy.user_ids, agent_policy.roles, context
        ):
            return "IDENTITY_SCOPE_DENIED"
        return ""

    def _evaluate_named_rules(
        self,
        rules: list[ToolPolicy],
        context: IdentityContext,
        server_name: str,
        item_name: str,
        kind: str,
    ) -> SecurityDecision:
        if not rules:
            return self._denial(
                f"{kind.upper()}_NOT_ALLOWED",
                f"No policy for {kind}",
                context,
                server_name,
                item_name,
            )
        matching_scopes = [rule for rule in rules if self._scope_allows(rule, context)]
        if any(rule.action == PolicyAction.DENY for rule in matching_scopes):
            return self._denial(
                f"{kind.upper()}_DENIED",
                f"{kind.capitalize()} is explicitly denied",
                context,
                server_name,
                item_name,
            )
        if any(rule.action == PolicyAction.APPROVAL_REQUIRED for rule in matching_scopes):
            return SecurityDecision(
                allowed=False,
                decision=DECISION_APPROVAL_REQUIRED,
                reason_code=REASON_APPROVAL_REQUIRED,
                reason_message=f"{kind.capitalize()} requires approval",
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server_name=server_name,
                tool_name=item_name,
            )
        if any(rule.action == PolicyAction.ALLOW for rule in matching_scopes):
            return SecurityDecision(
                allowed=True,
                decision=DECISION_ALLOW,
                reason_code=f"{kind.upper()}_ALLOWED",
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server_name=server_name,
                tool_name=item_name,
            )
        return self._denial(
            "IDENTITY_SCOPE_DENIED",
            f"Verified identity context is outside the {kind} policy scope",
            context,
            server_name,
            item_name,
        )

    @staticmethod
    def _scope_allows(rule: ToolPolicy, context: IdentityContext) -> bool:
        return PolicyEngine._scope_lists_allow(rule.tenant_ids, rule.user_ids, rule.roles, context)

    @staticmethod
    def _scope_lists_allow(
        tenant_ids: list[str], user_ids: list[str], roles: list[str], context: IdentityContext
    ) -> bool:
        if tenant_ids and context.tenant_id not in tenant_ids:
            return False
        if user_ids and context.user_id not in user_ids:
            return False
        return not roles or bool(set(roles).intersection(context.roles))

    @staticmethod
    def _render_uri_template(template: str, context: IdentityContext) -> str:
        values = {
            "agent_id": context.agent_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
        }
        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", quote(value, safe=""))
        if "{" in rendered or "}" in rendered:
            return ""
        return rendered

    def _context_for_agent(
        self,
        agent_id: str,
        tenant_id: str = "",
        user_id: str = "",
        roles: Optional[list[str]] = None,
    ) -> IdentityContext:
        identity = self._find_identity(agent_id)
        return IdentityContext(
            agent_id=agent_id,
            tenant_id=tenant_id or (identity.tenant_id if identity else ""),
            user_id=user_id or (identity.user_id if identity else ""),
            roles=list(roles) if roles else (list(identity.roles) if identity else []),
        )

    def _find_identity(self, agent_id: str) -> Optional[AgentIdentity]:
        identity = self._identity_agents.get(agent_id)
        if identity is not None:
            return identity
        return next((item for item in self._identity_agents.values() if item.id == agent_id), None)

    @staticmethod
    def _denial(
        reason_code: str,
        message: str,
        context: IdentityContext,
        server_name: str,
        item_name: str,
    ) -> SecurityDecision:
        return SecurityDecision(
            allowed=False,
            decision=DECISION_DENY,
            reason_code=reason_code,
            reason_message=message,
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            server_name=server_name,
            tool_name=item_name,
        )

    def _validate_arguments(
        self, arguments: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str]:
        """Validate arguments against JSON Schema, failing closed on bad schemas."""
        try:
            jsonschema.validate(instance=arguments, schema=schema)
            return True, ""
        except jsonschema.ValidationError as error:
            return False, str(error.message)
        except jsonschema.SchemaError as error:
            logger.error("Invalid JSON Schema in policy: %s", error)
            return False, "Invalid argument constraint schema"

    @staticmethod
    def _identity_arguments_match(
        bindings: dict[str, str], arguments: dict[str, Any], context: IdentityContext
    ) -> bool:
        """Require configured argument fields to equal trusted identity claims."""
        for argument_name, identity_field in bindings.items():
            expected = getattr(context, identity_field, None)
            actual = arguments.get(argument_name)
            if not isinstance(expected, str) or not expected:
                return False
            if not isinstance(actual, str) or actual != expected:
                return False
        return True
