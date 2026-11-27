"""Route MCP messages through shared identity, policy, and DLP checks."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from mcp_guard.core.constants import DECISION_DENY, METHOD_TOOLS_CALL, METHOD_TOOLS_LIST
from mcp_guard.core.exceptions import DLPViolationError, PolicyViolationError, ProtocolError
from mcp_guard.core.models import GatewayConfig, IdentityContext, SecurityDecision
from mcp_guard.protocol.inspector import MessageInspector
from mcp_guard.protocol.parser import (
    create_error_response,
    parse_message,
    parse_message_permissive,
)
from mcp_guard.protocol.validator import MessageValidator
from mcp_guard.security.tool_controller import ToolAccessController

logger = logging.getLogger("mcp_guard.router")

_SAFE_LIFECYCLE_REQUESTS = {"initialize", "ping"}
_SAFE_NOTIFICATIONS = {
    "notifications/initialized",
    "notifications/cancelled",
    "notifications/progress",
    "notifications/roots/list_changed",
}
_DISCOVERY_METHODS = {
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
}
_TASK_METHODS = {"tasks/get", "tasks/update", "tasks/cancel"}


class MessageRouter:
    """Transport-independent MCP security boundary."""

    def __init__(self, config: GatewayConfig, tool_controller: ToolAccessController) -> None:
        self.config = config
        self.inspector = MessageInspector()
        self.validator = MessageValidator(max_message_size=config.security.max_message_size)
        self.tool_controller = tool_controller

    def process_request(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext] = None,
        approval_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Authorize a request or notification and return its forward/error form."""
        start_time = time.monotonic()
        ok, reason = self.validator.validate_size(raw)
        if not ok:
            logger.warning("Message too large from agent=%s", agent_id)
            return None, create_error_response(None, -32600, reason or "Message too large")

        try:
            msg = parse_message(raw)
        except ProtocolError as exc:
            logger.warning("Malformed message from agent=%s: %s", agent_id, exc)
            return None, create_error_response(None, -32700, "Parse error")

        ok, reason = self.validator.validate_structure(msg)
        if not ok:
            logger.warning("Invalid JSON-RPC from agent=%s: %s", agent_id, reason)
            return None, create_error_response(msg.id, -32600, reason or "Invalid request")

        if msg.method == METHOD_TOOLS_CALL and not msg.is_request:
            return None, create_error_response(
                None, -32600, "tools/call must be sent as a JSON-RPC request"
            )
        if msg.is_response:
            return None, create_error_response(
                msg.id, -32600, "Client messages must be requests or notifications"
            )

        method = msg.method or ""
        params = msg.params or {}

        # Preserve protocol control messages needed by legacy MCP clients.
        if method in _SAFE_LIFECYCLE_REQUESTS:
            return raw, None
        if msg.is_notification:
            if method in _SAFE_NOTIFICATIONS:
                return raw, None
            decision = self.tool_controller.check_method(agent_id, server_name, method, context)
            return (raw, None) if decision.allowed else (None, None)

        if method in _DISCOVERY_METHODS:
            return raw, None

        if method == METHOD_TOOLS_CALL:
            tool_call = self.inspector.extract_tool_call(msg, server_name, agent_id)
            if tool_call is None:
                return None, create_error_response(msg.id, -32602, "Invalid tool call parameters")
            tool_call.identity_context = context or self.tool_controller.context_for_agent(agent_id)
            if tool_call.identity_context:
                tool_call.tenant_id = tool_call.identity_context.tenant_id
                tool_call.user_id = tool_call.identity_context.user_id
                tool_call.roles = list(tool_call.identity_context.roles)
            approval_id = approval_id or self._approval_id_from_params(params)
            try:
                decision = self.tool_controller.check_tool_call(tool_call)
            except PolicyViolationError as exc:
                decision = SecurityDecision(
                    allowed=False,
                    decision=DECISION_DENY,
                    reason_code=exc.reason_code,
                    reason_message=str(exc),
                    agent_id=agent_id,
                    server_name=server_name,
                    tool_name=tool_call.tool_name,
                    latency_ms=(time.monotonic() - start_time) * 1000,
                )
            except Exception:
                logger.exception("Policy evaluation failed closed")
                decision = SecurityDecision(
                    allowed=False,
                    decision=DECISION_DENY,
                    reason_code="POLICY_EVALUATION_ERROR",
                    reason_message="Policy evaluation failed",
                    agent_id=agent_id,
                    server_name=server_name,
                    tool_name=tool_call.tool_name,
                    latency_ms=(time.monotonic() - start_time) * 1000,
                )
            if not decision.allowed and decision.reason_code == "APPROVAL_REQUIRED":
                if approval_id:
                    resolved_context = tool_call.identity_context or IdentityContext(
                        agent_id=agent_id,
                        tenant_id=tool_call.tenant_id,
                        user_id=tool_call.user_id,
                        roles=tool_call.roles,
                    )
                    matched, reason_code = self.tool_controller.consume_approval(
                        approval_id, tool_call, resolved_context
                    )
                    if not matched:
                        decision.reason_code = reason_code
                        decision.reason_message = "Approval is invalid, expired, or already used"
                        return None, self._denial_response(msg.id, decision)
                    decision = self.tool_controller.check_tool_call(
                        tool_call, approval_accepted=True
                    )
                else:
                    try:
                        record = self.tool_controller.create_approval(tool_call)
                    except OverflowError:
                        return None, create_error_response(
                            msg.id, -32001, "Approval queue is full; operation denied"
                        )
                    return None, create_error_response(
                        msg.id,
                        -32001,
                        "Approval required: this operation is waiting for an administrator",
                        {
                            "reason": "APPROVAL_REQUIRED",
                            "approval_id": record["approval_id"],
                            "state": record["state"],
                            "expires_at": record["expires_at"],
                        },
                    )
            if not decision.allowed:
                return None, self._denial_response(msg.id, decision)
            self.tool_controller.record_tool_call(server_name, tool_call, decision)
            return self._dlp_request(
                self._strip_approval_metadata(raw),
                agent_id,
                server_name,
                method,
                msg.id,
                tool_call.identity_context,
            )

        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str) or not uri:
                return None, create_error_response(msg.id, -32602, "Invalid resource URI")
            decision = self.tool_controller.check_resource_read(agent_id, server_name, uri, context)
            if not decision.allowed:
                return None, self._denial_response(msg.id, decision)
            return self._dlp_request(raw, agent_id, server_name, method, msg.id, context)

        if method == "prompts/get":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                return None, create_error_response(msg.id, -32602, "Invalid prompt parameters")
            decision = self.tool_controller.check_prompt_get(
                agent_id, server_name, name, arguments, context
            )
            if not decision.allowed:
                return None, self._denial_response(msg.id, decision)
            return self._dlp_request(raw, agent_id, server_name, method, msg.id, context)

        if method in _TASK_METHODS:
            task_id = params.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                return None, create_error_response(msg.id, -32602, "Invalid task ID")
            method_decision = self.tool_controller.check_method(
                agent_id, server_name, method, context
            )
            if not method_decision.allowed:
                return None, self._denial_response(msg.id, method_decision)
            decision = self.tool_controller.check_task_operation(
                task_id, agent_id, server_name, method, context
            )
            if not decision.allowed:
                return None, self._denial_response(msg.id, decision)
            return self._dlp_request(raw, agent_id, server_name, method, msg.id, context)

        if method == "subscriptions/listen":
            decision = self.tool_controller.check_method(agent_id, server_name, method, context)
            if not decision.allowed:
                return None, self._denial_response(msg.id, decision)
            filtered_params, error = self._filter_subscription_params(
                params, agent_id, server_name, context
            )
            if error:
                return None, create_error_response(msg.id, -32602, error)
            message = json.loads(raw)
            message["params"] = filtered_params
            return self._dlp_request(
                json.dumps(message, separators=(",", ":"), ensure_ascii=False),
                agent_id,
                server_name,
                method,
                msg.id,
                context,
            )

        # Extensions and unknown valid requests are explicit opt-in. This also
        # keeps legacy operations usable when an administrator grants them.
        decision = self.tool_controller.check_method(agent_id, server_name, method, context)
        if not decision.allowed:
            return None, self._denial_response(msg.id, decision)
        return self._dlp_request(raw, agent_id, server_name, method, msg.id, context)

    def _dlp_request(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        method: str,
        request_id: Any,
        context: Optional[IdentityContext] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        try:
            return self.tool_controller.dlp_check_request(
                raw, agent_id, server_name, method, context
            ), None
        except DLPViolationError:
            self.tool_controller.clear_pending_tool_call(server_name, agent_id, request_id)
            return None, create_error_response(
                request_id, -32001, "Request blocked by data-protection policy"
            )

    def process_response(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        pending_method: Optional[str] = None,
        context: Optional[IdentityContext] = None,
        request_id: Any = None,
    ) -> str:
        """Process an upstream response and return its safe form."""
        return self.process_response_with_decision(
            raw, agent_id, server_name, pending_method, context, request_id
        )[0]

    def process_response_with_decision(
        self,
        raw: str,
        agent_id: str,
        server_name: str,
        pending_method: Optional[str] = None,
        context: Optional[IdentityContext] = None,
        request_id: Any = None,
    ) -> tuple[str, str]:
        """Filter discoveries, bind task IDs to their caller, and inspect DLP."""
        ok, reason = self.validator.validate_size(raw)
        if not ok:
            logger.warning("Oversized response from server=%s", server_name)
            try:
                data = json.loads(raw)
                response_id = data.get("id") if isinstance(data, dict) else None
            except Exception:
                response_id = None
            return create_error_response(
                response_id, -32001, "Response too large"
            ), "RESPONSE_TOO_LARGE"

        if not raw:
            return raw, ""
        parsed = parse_message_permissive(raw)
        if parsed is None:
            logger.warning("Rejected malformed JSON-RPC response from server=%s", server_name)
            return (
                create_error_response(None, -32603, "Upstream returned an invalid MCP message"),
                "UPSTREAM_INVALID_MESSAGE",
            )

        reason_code = ""
        try:
            data = json.loads(raw)
            allowed_context = context or self.tool_controller.context_for_agent(agent_id)
            if pending_method == "subscriptions/listen" and parsed.is_notification:
                filtered_event = self._filter_subscription_event(
                    data, agent_id, server_name, allowed_context
                )
                if filtered_event is None:
                    return "", "SUBSCRIPTION_EVENT_FILTERED"
                data = filtered_event
                reason_code = "SUBSCRIPTION_EVENT_FILTERED"
            elif pending_method == METHOD_TOOLS_LIST:
                allowed = self.tool_controller.get_allowed_tools(
                    agent_id, server_name, allowed_context
                )
                data = self.inspector.filter_tools_list_response(data, allowed)
                reason_code = "TOOLS_LIST_FILTERED"
            elif pending_method == "resources/list":
                result = self._result_mapping(data)
                items = result.get("resources")
                if isinstance(items, list):
                    allowed_names = set(
                        self.tool_controller.get_allowed_resources(
                            agent_id, server_name, allowed_context
                        )
                    )
                    result["resources"] = [
                        item
                        for item in items
                        if isinstance(item, dict) and item.get("uri") in allowed_names
                    ]
                    result.pop("nextCursor", None)
                    reason_code = "RESOURCES_LIST_FILTERED"
            elif pending_method == "resources/templates/list":
                result = self._result_mapping(data)
                items = result.get("resourceTemplates")
                if isinstance(items, list):
                    allowed_names = set(
                        self.tool_controller.get_allowed_resource_templates(
                            agent_id, server_name, allowed_context
                        )
                    )
                    result["resourceTemplates"] = [
                        item
                        for item in items
                        if isinstance(item, dict) and item.get("uriTemplate") in allowed_names
                    ]
                    result.pop("nextCursor", None)
                    reason_code = "RESOURCE_TEMPLATES_FILTERED"
            elif pending_method == "prompts/list":
                result = self._result_mapping(data)
                items = result.get("prompts")
                if isinstance(items, list):
                    allowed_names = set(
                        self.tool_controller.get_allowed_prompts(
                            agent_id, server_name, allowed_context
                        )
                    )
                    result["prompts"] = [
                        item
                        for item in items
                        if isinstance(item, dict) and item.get("name") in allowed_names
                    ]
                    result.pop("nextCursor", None)
                    reason_code = "PROMPTS_LIST_FILTERED"
            elif pending_method == "server/discover":
                result = self._result_mapping(data)
                servers = result.get("servers")
                if isinstance(servers, list):
                    allowed_names = set(self.tool_controller.get_allowed_servers(agent_id))
                    result["servers"] = [
                        server
                        for server in servers
                        if isinstance(server, dict) and server.get("name") in allowed_names
                    ]
                    result.pop("nextCursor", None)
                    reason_code = "SERVER_DISCOVERY_FILTERED"
            else:
                data = None
            if data is not None and reason_code:
                raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            logger.exception("Failed to filter MCP discovery response; replacing with empty result")
            if pending_method in _DISCOVERY_METHODS:
                return (
                    create_error_response(parsed.id, -32001, "Discovery filtering failed closed"),
                    "DISCOVERY_FILTER_ERROR",
                )

        try:
            before_dlp = raw
            raw = self.tool_controller.dlp_check_response(
                raw, agent_id, server_name, pending_method or "", context
            )
            if raw != before_dlp:
                reason_code = "DLP_REDACTED"
        except DLPViolationError:
            return (
                create_error_response(
                    parsed.id, -32001, "Response blocked by data-protection policy"
                ),
                "DLP_BLOCKED",
            )

        if pending_method == METHOD_TOOLS_CALL and request_id is not None:
            self.tool_controller.record_task_response(
                raw,
                pending_method,
                agent_id,
                server_name,
                context,
                request_id,
            )
        return raw, reason_code

    def _filter_subscription_event(
        self,
        message: dict[str, Any],
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext],
    ) -> Optional[dict[str, Any]]:
        """Filter notifications carried on an authorized subscriptions stream."""
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return None
        if method == "notifications/resources/updated":
            uri = params.get("uri")
            if not isinstance(uri, str):
                return None
            decision = self.tool_controller.check_resource_read(agent_id, server_name, uri, context)
            return message if decision.allowed else None
        if method == "notifications/tasks":
            task = params.get("task")
            task_id = params.get("taskId")
            if not isinstance(task_id, str) and isinstance(task, dict):
                task_id = task.get("taskId")
            if not isinstance(task_id, str):
                return None
            if not self.tool_controller.check_method(
                agent_id, server_name, "tasks/get", context
            ).allowed:
                return None
            decision = self.tool_controller.check_task_operation(
                task_id, agent_id, server_name, "tasks/get", context
            )
            return message if decision.allowed else None
        if method == "notifications/subscriptions/acknowledged":
            notifications = params.get("notifications")
            if not isinstance(notifications, dict):
                return None
            allowed_resources = set(
                self.tool_controller.get_allowed_resources(agent_id, server_name, context)
            )
            filtered = dict(notifications)
            requested = filtered.get("resourceSubscriptions", [])
            if isinstance(requested, list):
                filtered["resourceSubscriptions"] = [
                    uri for uri in requested if isinstance(uri, str) and uri in allowed_resources
                ]
            for flag, visible in (
                (
                    "toolsListChanged",
                    bool(self.tool_controller.get_allowed_tools(agent_id, server_name, context)),
                ),
                (
                    "promptsListChanged",
                    bool(self.tool_controller.get_allowed_prompts(agent_id, server_name, context)),
                ),
                ("resourcesListChanged", bool(allowed_resources)),
            ):
                if filtered.get(flag) and not visible:
                    filtered[flag] = False
            new_message = dict(message)
            new_params = dict(params)
            new_params["notifications"] = filtered
            new_message["params"] = new_params
            return new_message
        visibility = {
            "notifications/tools/list_changed": bool(
                self.tool_controller.get_allowed_tools(agent_id, server_name, context)
            ),
            "notifications/prompts/list_changed": bool(
                self.tool_controller.get_allowed_prompts(agent_id, server_name, context)
            ),
            "notifications/resources/list_changed": bool(
                self.tool_controller.get_allowed_resources(agent_id, server_name, context)
            ),
        }
        if method in visibility:
            return message if visibility[method] else None
        return (
            message
            if self.tool_controller.check_method(agent_id, server_name, method, context).allowed
            else None
        )

    def _filter_subscription_params(
        self,
        params: dict[str, Any],
        agent_id: str,
        server_name: str,
        context: Optional[IdentityContext],
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Remove subscription filters for resources outside the caller's grants."""
        notifications = params.get("notifications")
        if not isinstance(notifications, dict):
            return {}, "subscriptions/listen requires a notifications object"
        result = dict(params)
        filtered = dict(notifications)
        if "resourceSubscriptions" in filtered:
            requested = filtered["resourceSubscriptions"]
            if not isinstance(requested, list) or any(
                not isinstance(uri, str) for uri in requested
            ):
                return {}, "resourceSubscriptions must be a list of resource URIs"
            allowed = set(
                self.tool_controller.get_allowed_resources(agent_id, server_name, context)
            )
            filtered["resourceSubscriptions"] = [uri for uri in requested if uri in allowed]
        for flag, visible in (
            (
                "toolsListChanged",
                bool(self.tool_controller.get_allowed_tools(agent_id, server_name, context)),
            ),
            (
                "promptsListChanged",
                bool(self.tool_controller.get_allowed_prompts(agent_id, server_name, context)),
            ),
            (
                "resourcesListChanged",
                bool(self.tool_controller.get_allowed_resources(agent_id, server_name, context)),
            ),
        ):
            if filtered.get(flag) and not visible:
                filtered[flag] = False
        result["notifications"] = filtered
        return result, None

    @staticmethod
    def _result_mapping(data: dict[str, Any]) -> dict[str, Any]:
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValueError("response has no result object")
        return result

    @staticmethod
    def _denial_response(request_id: Any, decision: SecurityDecision) -> str:
        message = (
            "Approval required: this operation needs administrator approval"
            if decision.reason_code == "APPROVAL_REQUIRED"
            else "Access denied: policy does not permit this operation"
        )
        return create_error_response(
            request_id,
            -32001,
            message,
            {"reason": decision.reason_code},
        )

    @staticmethod
    def _approval_id_from_params(params: dict[str, Any]) -> Optional[str]:
        metadata = params.get("_meta")
        if not isinstance(metadata, dict):
            return None
        approval_id = metadata.get("io.mcp-guard/approvalId")
        return approval_id if isinstance(approval_id, str) and approval_id else None

    @staticmethod
    def _strip_approval_metadata(raw: str) -> str:
        """Remove gateway control metadata before forwarding to the MCP server."""
        try:
            message = json.loads(raw)
            params = message.get("params")
            if not isinstance(params, dict):
                return raw
            metadata = params.get("_meta")
            if not isinstance(metadata, dict) or "io.mcp-guard/approvalId" not in metadata:
                return raw
            metadata = dict(metadata)
            metadata.pop("io.mcp-guard/approvalId", None)
            if metadata:
                params["_meta"] = metadata
            else:
                params.pop("_meta", None)
            return json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        except (json.JSONDecodeError, AttributeError, TypeError):
            return raw
