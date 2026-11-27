"""Shared access controller for protected MCP operations and DLP."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from mcp_guard.approval.service import ApprovalService
from mcp_guard.core.models import (
    GatewayConfig,
    IdentityContext,
    SecurityDecision,
    ToolCallInfo,
)
from mcp_guard.identity.manager import IdentityManager
from mcp_guard.policies.engine import PolicyEngine
from mcp_guard.policies.runtime import RuntimePolicyManager
from mcp_guard.security.dlp import DLPEngine

logger = logging.getLogger("mcp_guard.access_controller")

MAX_TASK_OWNERS = 10_000
DEFAULT_TASK_OWNERSHIP_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class _TaskOwner:
    context: IdentityContext
    tool_name: str
    arguments: dict[str, Any]
    expires_at: float


class AccessController:
    """One synchronous security boundary shared by every transport.

    The controller owns identity resolution, policy evaluation, task ownership,
    and DLP entry points. It does not trust identity values from MCP arguments.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.identity_manager = IdentityManager(config)
        self.policy_engine = PolicyEngine(config)
        self.policy_manager = RuntimePolicyManager(config, self.policy_engine)
        self.approval_service = ApprovalService(config.security.approval_timeout_seconds)
        self.dlp_engine = DLPEngine(config)
        self._task_owners: dict[tuple[str, str], _TaskOwner] = {}
        self._pending_task_calls: dict[
            tuple[str, str, str], tuple[IdentityContext, str, dict[str, Any]]
        ] = {}
        self._task_lock = threading.Lock()

    def context_for_agent(self, agent_id: str) -> Optional[IdentityContext]:
        """Return the administrator-configured context for a STDIO agent."""
        return self.identity_manager.get_context_for_agent(agent_id)

    def get_identity_context(self, agent_id: str) -> Optional[IdentityContext]:
        """Resolve a configured identity for transports without per-request auth."""
        return self.identity_manager.get_context_for_agent(agent_id)

    def check_tool_call(
        self, tool_call: ToolCallInfo, approval_accepted: bool = False
    ) -> SecurityDecision:
        """Check a tool call against agent, tenant, user, role, and tool rules."""
        start_time = time.monotonic()
        decision = self.policy_engine.evaluate(tool_call, approval_accepted)
        decision.latency_ms = (time.monotonic() - start_time) * 1000
        return decision

    def create_approval(self, tool_call: ToolCallInfo) -> dict[str, Any]:
        """Queue a policy-required tool action for an administrator."""
        return self.approval_service.create(tool_call)

    def consume_approval(
        self, approval_id: str, tool_call: ToolCallInfo, context: IdentityContext
    ) -> tuple[bool, str]:
        """Validate and consume a one-time approval for this action."""
        return self.approval_service.authorize_once(approval_id, tool_call, context)

    def check_resource_read(
        self,
        agent_id: str,
        server_name: str,
        uri: str,
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize a resource URI, including requests constructed by hand."""
        return self.policy_engine.evaluate_resource(agent_id, server_name, uri, context)

    def check_prompt_get(
        self,
        agent_id: str,
        server_name: str,
        name: str,
        arguments: dict[str, Any],
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize prompt retrieval and validate prompt arguments."""
        return self.policy_engine.evaluate_prompt(agent_id, server_name, name, arguments, context)

    def check_method(
        self,
        agent_id: str,
        server_name: str,
        method: str,
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize an extension method only when explicitly configured."""
        return self.policy_engine.evaluate_method(agent_id, server_name, method, context)

    def get_allowed_tools(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        return self.policy_engine.get_allowed_tools(agent_id, server_name, context)

    def get_allowed_prompts(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        return self.policy_engine.get_allowed_prompts(agent_id, server_name, context)

    def get_allowed_resources(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        return self.policy_engine.get_allowed_resources(agent_id, server_name, context)

    def get_allowed_resource_templates(
        self,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
    ) -> list[str]:
        return self.policy_engine.get_allowed_resource_templates(agent_id, server_name, context)

    def get_allowed_servers(self, agent_id: str) -> list[str]:
        """Return the configured server set visible to an agent."""
        return self.policy_engine.get_allowed_servers(agent_id)

    def check_task_operation(
        self,
        task_id: str,
        agent_id: str,
        server_name: str,
        method: str,
        context: Optional[IdentityContext] = None,
    ) -> SecurityDecision:
        """Authorize task access only for the identity that created it.

        Task IDs are opaque and server-issued. Unknown tasks and tasks created
        before this process started fail closed. The original tool policy is
        re-evaluated on every task operation so revocations take effect.
        """
        resolved = context or self.context_for_agent(agent_id)
        if resolved is None:
            resolved = IdentityContext(agent_id=agent_id)
        owner = self._get_task_owner(server_name, task_id)
        if owner is None:
            return self._deny(
                "TASK_NOT_OWNED",
                "Task is unknown or is not owned by this identity",
                resolved,
                server_name,
                task_id,
            )
        if (
            owner.context.agent_id != resolved.agent_id
            or owner.context.tenant_id != resolved.tenant_id
            or owner.context.user_id != resolved.user_id
            or set(owner.context.roles) != set(resolved.roles)
        ):
            return self._deny(
                "TASK_NOT_OWNED",
                "Task is unknown or is not owned by this identity",
                resolved,
                server_name,
                task_id,
            )

        decision = self.policy_engine.evaluate(
            ToolCallInfo(
                request_id=None,
                tool_name=owner.tool_name,
                arguments=owner.arguments,
                server_name=server_name,
                agent_id=resolved.agent_id,
                tenant_id=resolved.tenant_id,
                user_id=resolved.user_id,
                roles=resolved.roles,
                identity_context=resolved,
            )
        )
        if not decision.allowed:
            return decision
        decision.tool_name = method
        decision.reason_code = "TASK_ACCESS_ALLOWED"
        return decision

    def record_task_response(
        self,
        raw: str,
        pending_method: Optional[str],
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
        request_id: Any = None,
    ) -> None:
        """Bind a server-created task ID to the verified originating caller."""
        pending_key = self._pending_key(server_name, agent_id, request_id)
        with self._task_lock:
            origin = self._pending_task_calls.pop(pending_key, None)
        if pending_method != "tools/call" or origin is None:
            return
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(message, dict):
            return
        result = message.get("result")
        if not isinstance(result, dict) or result.get("resultType") != "task":
            return
        task_id = result.get("taskId")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 512:
            return
        resolved, tool_name, arguments = origin
        if context is not None and context != resolved:
            return
        ttl_ms = result.get("ttlMs")
        ttl_seconds = (
            min(max(ttl_ms / 1000, 1), DEFAULT_TASK_OWNERSHIP_TTL_SECONDS)
            if isinstance(ttl_ms, int) and not isinstance(ttl_ms, bool) and ttl_ms > 0
            else DEFAULT_TASK_OWNERSHIP_TTL_SECONDS
        )
        with self._task_lock:
            self._task_owners[(server_name, task_id)] = _TaskOwner(
                context=resolved,
                tool_name=tool_name,
                arguments=arguments,
                expires_at=time.monotonic() + ttl_seconds,
            )
            while len(self._task_owners) > MAX_TASK_OWNERS:
                self._task_owners.pop(next(iter(self._task_owners)))

    def record_tool_call(
        self, server_name: str, tool_call: ToolCallInfo, decision: SecurityDecision
    ) -> None:
        """Remember an allowed call long enough to bind any task result to it."""
        key = self._pending_key(server_name, tool_call.agent_id, tool_call.request_id)
        context = tool_call.identity_context or self.context_for_agent(tool_call.agent_id)
        with self._task_lock:
            if decision.allowed and context is not None:
                self._pending_task_calls[key] = (
                    context,
                    tool_call.tool_name,
                    dict(tool_call.arguments),
                )
                while len(self._pending_task_calls) > MAX_TASK_OWNERS:
                    self._pending_task_calls.pop(next(iter(self._pending_task_calls)))

    def clear_pending_tool_call(self, server_name: str, agent_id: str, request_id: Any) -> None:
        """Drop transient task binding after a tool response without a task."""
        with self._task_lock:
            self._pending_task_calls.pop(self._pending_key(server_name, agent_id, request_id), None)

    def _get_task_owner(self, server_name: str, task_id: str) -> Optional[_TaskOwner]:
        key = (server_name, task_id)
        with self._task_lock:
            owner = self._task_owners.get(key)
            if owner and owner.expires_at <= time.monotonic():
                self._task_owners.pop(key, None)
                return None
            return owner

    @staticmethod
    def _pending_key(server_name: str, agent_id: str, request_id: Any) -> tuple[str, str, str]:
        """Create a stable key for JSON-RPC string or numeric IDs."""
        try:
            rendered_id = json.dumps(request_id, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            rendered_id = repr(request_id)
        return server_name, agent_id, rendered_id

    def dlp_check_request(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        method: str = "tools/call",
        context: Optional[IdentityContext] = None,
    ) -> str:
        """Inspect a request with configured DLP rules."""
        resolved_context = context or self.context_for_agent(agent_id)
        return self.dlp_engine.inspect_message(
            raw,
            agent_id,
            server_name,
            direction="request",
            method=method,
            context=resolved_context,
        )

    def dlp_check_response(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        method: str = "",
        context: Optional[IdentityContext] = None,
    ) -> str:
        """Inspect a response with configured DLP rules."""
        resolved_context = context or self.context_for_agent(agent_id)
        return self.dlp_engine.inspect_message(
            raw,
            agent_id,
            server_name,
            direction="response",
            method=method,
            context=resolved_context,
        )

    @staticmethod
    def _deny(
        reason_code: str,
        reason_message: str,
        context: IdentityContext,
        server_name: str,
        item_name: str,
    ) -> SecurityDecision:
        return SecurityDecision(
            allowed=False,
            decision="DENY",
            reason_code=reason_code,
            reason_message=reason_message,
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            server_name=server_name,
            tool_name=item_name,
        )


# Backward-compatible public name used by existing integrations.
ToolAccessController = AccessController
