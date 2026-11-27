"""Streamable HTTP gateway with bounded response inspection.

JSON responses are buffered up to the configured message limit. SSE responses
are inspected event by event and remain streamed to the downstream client.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import ssl
import time
import uuid
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from mcp_guard import __version__
from mcp_guard.audit.logger import AuditLogger
from mcp_guard.core.constants import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_REDACT,
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    METHOD_TOOLS_CALL,
)
from mcp_guard.core.exceptions import ConfigurationError, DLPViolationError
from mcp_guard.core.models import (
    GatewayConfig,
    IdentityContext,
    JSONRPCMessage,
    PolicyConfig,
    ToolCallInfo,
)
from mcp_guard.observability.metrics import MetricsRegistry
from mcp_guard.observability.tracing import TracingManager
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.protocol.parser import create_error_response, parse_message_permissive
from mcp_guard.security.tool_controller import ToolAccessController
from mcp_guard.transports.base import BaseTransport

logger = logging.getLogger("mcp_guard.http")

PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
CURRENT_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_MODERN_VERSIONS = [CURRENT_PROTOCOL_VERSION]
SUPPORTED_LEGACY_HTTP_VERSIONS = {
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
}
SUPPORTED_PROTOCOL_VERSIONS = [CURRENT_PROTOCOL_VERSION, *sorted(SUPPORTED_LEGACY_HTTP_VERSIONS)]
RESPONSE_HEADERS = {
    "cache-control",
    "mcp-session-id",
    "mcp-protocol-version",
    "x-accel-buffering",
}
FORWARDED_REQUEST_HEADERS = {
    "mcp-protocol-version",
    "mcp-method",
    "mcp-name",
    "mcp-session-id",
    "origin",
}


class HTTPTransport(BaseTransport):
    """Authenticated HTTP adapter for an upstream MCP endpoint."""

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self.tool_controller = ToolAccessController(config)
        self.identity_manager = self.tool_controller.identity_manager
        self.message_router = MessageRouter(config, self.tool_controller)
        self.audit_logger = AuditLogger(config)
        self.metrics = MetricsRegistry()
        self.tracing = TracingManager(config.name)

        self.host = DEFAULT_HTTP_HOST
        self.port = DEFAULT_HTTP_PORT
        self.upstream_url = ""
        self.allowed_origins: list[str] = []
        self.upstream_headers: dict[str, str] = {}
        if config.http:
            self.host = config.http.host
            self.port = config.http.port
            self.upstream_url = config.http.upstream_url
            self.allowed_origins = config.http.allowed_origins
            self.upstream_headers = dict(config.http.upstream_headers)

        self.max_message_size = config.security.max_message_size
        self.request_timeout = config.security.request_timeout_seconds
        self._app: Optional[Starlette] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tool_header_parameters: dict[tuple[str, str], dict[str, str]] = {}
        self._upstream_reachable: Optional[bool] = None

    def create_app(self) -> Starlette:
        """Create the Starlette ASGI application."""
        self._app = Starlette(
            routes=[
                Route("/mcp", self._handle_mcp, methods=["POST"]),
                Route("/api/v1/actions/{action:str}", self._handle_rest_action, methods=["POST"]),
                Route("/admin", self._handle_dashboard, methods=["GET"]),
                Route("/admin/", self._handle_dashboard, methods=["GET"]),
                Mount(
                    "/admin/assets",
                    app=StaticFiles(
                        directory=str(files("mcp_guard").joinpath("static")), check_dir=False
                    ),
                    name="admin-assets",
                ),
                Route("/health", self._handle_health, methods=["GET"]),
                Route("/health/live", self._handle_health, methods=["GET"]),
                Route("/health/ready", self._handle_readiness, methods=["GET"]),
                Route("/metrics", self._handle_metrics, methods=["GET"]),
                Route("/admin/session", self._admin_session, methods=["GET"]),
                Route("/admin/agents", self._list_agents, methods=["GET"]),
                Route("/admin/servers", self._list_servers, methods=["GET"]),
                Route("/admin/dlp", self._get_dlp, methods=["GET"]),
                Route("/admin/audit", self._list_audit_events, methods=["GET"]),
                Route("/admin/settings", self._get_settings, methods=["GET"]),
                Route("/admin/approvals", self._list_approvals, methods=["GET"]),
                Route(
                    "/admin/approvals/{approval_id:str}/decision",
                    self._decide_approval,
                    methods=["POST"],
                ),
                Route("/admin/policy", self._get_policy, methods=["GET"]),
                Route("/admin/policy", self._update_policy, methods=["PUT"]),
                Route(
                    "/admin/policy/rollback/{version:int}",
                    self._rollback_policy,
                    methods=["POST"],
                ),
                Route("/admin/tokens/revoke", self._revoke_token, methods=["POST"]),
                Route("/admin/tokens/rotate", self._rotate_token, methods=["POST"]),
            ]
        )
        return self._app

    async def start(self) -> None:
        """Start the local HTTP gateway."""
        import uvicorn

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.request_timeout),
            follow_redirects=False,
        )
        try:
            server = uvicorn.Server(
                uvicorn.Config(
                    self.create_app(),
                    host=self.host,
                    port=self.port,
                    log_level="warning",
                    ssl_certfile=(self.config.http.tls_cert_file if self.config.http else None),
                    ssl_keyfile=(self.config.http.tls_key_file if self.config.http else None),
                    ssl_ca_certs=(self.config.http.client_ca_file if self.config.http else None),
                    ssl_cert_reqs=(
                        ssl.CERT_REQUIRED
                        if self.config.http and self.config.http.require_client_certificate
                        else (
                            ssl.CERT_OPTIONAL
                            if self.config.http and self.config.http.client_ca_file
                            else ssl.CERT_NONE
                        )
                    ),
                )
            )
            logger.info("Starting HTTP gateway on %s:%d", self.host, self.port)
            await server.serve()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Close the outbound client and audit stream."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self.tracing.shutdown()
        self.audit_logger.close()

    async def _handle_health(self, request: Request) -> JSONResponse:
        """Unauthenticated local health endpoint."""
        return JSONResponse({"status": "ok", "version": __version__})

    async def _handle_readiness(self, request: Request) -> JSONResponse:
        """Report whether the configured gateway components are initialized."""
        ready = bool(
            self.message_router
            and self.tool_controller
            and self.upstream_url
            and self._upstream_reachable is not False
        )
        return JSONResponse(
            {
                "status": "ready" if ready else "not_ready",
                "upstream_configured": bool(self.upstream_url),
                "upstream_status": (
                    "unknown"
                    if self._upstream_reachable is None
                    else "available"
                    if self._upstream_reachable
                    else "unavailable"
                ),
                "policy_engine": "ok" if self.tool_controller.policy_engine else "unavailable",
                "dlp_engine": "ok" if self.tool_controller.dlp_engine else "unavailable",
            },
            status_code=200 if ready else 503,
        )

    async def _handle_metrics(self, request: Request) -> Response:
        """Expose low-cardinality metrics to authenticated administrators."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        return Response(self.metrics.render(), media_type="text/plain; version=0.0.4")

    async def _handle_dashboard(self, request: Request) -> Response:
        """Serve the credential-free admin UI; every data API remains authenticated."""
        html = files("mcp_guard").joinpath("static/index.html").read_text(encoding="utf-8")
        return Response(
            html,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
                    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _admin_session(self, request: Request) -> JSONResponse:
        """Validate an administrator token and return non-secret session details."""
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        return JSONResponse({"administrator_id": admin[0], "roles": admin[1]})

    async def _list_agents(self, request: Request) -> JSONResponse:
        """Return configured agents without authentication hashes or raw credentials."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        agents = []
        for agent in self.config.identity.agents.values():
            tenant_ids = sorted(
                {
                    item.tenant_id
                    for item in self.config.identity.credentials.values()
                    if item.agent_id == agent.id and item.tenant_id
                }
                | ({agent.tenant_id} if agent.tenant_id else set())
            )
            agents.append(
                {
                    "id": agent.id,
                    "name": agent.name or agent.id,
                    "enabled": agent.enabled,
                    "tenant_ids": tenant_ids,
                    "roles": agent.roles,
                    "servers": agent.servers,
                    "authentication_configured": bool(agent.api_key_hash)
                    or any(
                        item.agent_id == agent.id
                        for item in self.config.identity.credentials.values()
                    ),
                    "last_activity": None,
                }
            )
        return JSONResponse({"agents": sorted(agents, key=lambda item: item["id"])})

    async def _list_servers(self, request: Request) -> JSONResponse:
        """Return safe summaries of configured upstreams, omitting headers and env."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        upstreams = dict(self.config.upstreams)
        if self.config.stdio:
            upstreams.setdefault(self.config.stdio.upstream.name, self.config.stdio.upstream)
        servers = []
        for key, upstream in sorted(upstreams.items()):
            if upstream.url:
                endpoint = self._safe_endpoint(upstream.url)
                transport = "http"
            elif upstream.command:
                endpoint = Path(upstream.command[0]).name
                transport = "stdio"
            else:
                endpoint = "Not configured"
                transport = "unknown"
            servers.append(
                {
                    "name": upstream.name or key,
                    "transport": transport,
                    "endpoint": endpoint,
                    "assigned_agents": sorted(
                        agent.id
                        for agent in self.config.identity.agents.values()
                        if key in agent.servers or upstream.name in agent.servers
                    ),
                    "status": self._server_status(transport),
                }
            )
        if self.config.http and self.config.http.upstream_url and not servers:
            servers.append(
                {
                    "name": "configured-upstream",
                    "transport": "http",
                    "endpoint": self._safe_endpoint(self.config.http.upstream_url),
                    "assigned_agents": [],
                    "status": self._server_status("http"),
                }
            )
        return JSONResponse({"servers": servers})

    async def _get_dlp(self, request: Request) -> JSONResponse:
        """Return configured DLP rule summaries; runtime rule editing is unsupported."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        patterns = self.config.security.dlp_patterns if self.config.security.enable_dlp else []
        return JSONResponse(
            {
                "enabled": self.config.security.enable_dlp,
                "runtime_editing_supported": False,
                "rules": [
                    {
                        "name": rule.name,
                        "pattern": rule.pattern[:512],
                        "action": rule.mode.value,
                        "replacement": rule.replacement,
                        "enabled": rule.enabled,
                        "agents": rule.agents,
                        "tenants": rule.tenant_ids,
                        "users": rule.user_ids,
                        "servers": rule.servers,
                        "methods": rule.methods,
                        "directions": rule.directions,
                    }
                    for rule in patterns
                ],
            }
        )

    async def _list_audit_events(self, request: Request) -> JSONResponse:
        """Read and filter a bounded tail of payload-free audit metadata."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        try:
            limit = int(request.query_params.get("limit", "50"))
            offset = int(request.query_params.get("offset", "0"))
        except ValueError:
            return JSONResponse({"error": "limit and offset must be integers"}, status_code=400)
        if limit < 1 or limit > 200 or offset < 0:
            return JSONResponse(
                {"error": "limit must be 1-200 and offset must be non-negative"},
                status_code=400,
            )
        path = Path(self.config.logging.file)
        window_bytes = 4 * 1024 * 1024
        truncated = False
        raw_events: list[dict[str, Any]] = []
        try:
            with path.open("rb") as audit_file:
                audit_file.seek(0, 2)
                size = audit_file.tell()
                start = max(0, size - window_bytes)
                truncated = start > 0
                audit_file.seek(start)
                data = audit_file.read(window_bytes + 1)
            lines = data.splitlines()
            if truncated and lines:
                lines = lines[1:]
            for line in lines:
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                safe = self._safe_audit_event(value)
                if safe is not None:
                    raw_events.append(safe)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Unable to read configured audit log")
            return JSONResponse({"error": "Audit log is currently unavailable"}, status_code=503)

        events = sorted(raw_events, key=lambda item: item["timestamp"], reverse=True)
        events = [item for item in events if self._audit_event_matches(item, request)]
        total = len(events)
        return JSONResponse(
            {
                "events": events[offset : offset + limit],
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total,
                "truncated": truncated,
                "source": "active_file",
            }
        )

    async def _get_settings(self, request: Request) -> JSONResponse:
        """Expose safe runtime settings without paths, credentials, or upstream headers."""
        if self._authenticate_admin(request) is None:
            return self._admin_unauthorized()
        http_config = self.config.http
        jwt_config = self.config.identity.jwt
        return JSONResponse(
            {
                "product": self.config.name,
                "environment": self.config.environment,
                "gateway_transport": self.config.transport,
                "listener": (
                    {"host": http_config.host, "port": http_config.port} if http_config else None
                ),
                "allowed_origins": http_config.allowed_origins if http_config else [],
                "jwt_enabled": bool(jwt_config and jwt_config.enabled),
                "mtls_enabled": bool(http_config and http_config.client_ca_file),
                "mtls_required": bool(http_config and http_config.require_client_certificate),
                "tls_server_certificate_configured": bool(
                    http_config and http_config.tls_cert_file and http_config.tls_key_file
                ),
                "security": {
                    "max_message_size": self.config.security.max_message_size,
                    "request_timeout_seconds": self.config.security.request_timeout_seconds,
                    "approval_timeout_seconds": self.config.security.approval_timeout_seconds,
                    "dlp_enabled": self.config.security.enable_dlp,
                },
                "audit": {
                    "enabled": bool(self.config.logging.file),
                    "max_size_mb": self.config.logging.max_size_mb,
                    "backup_count": self.config.logging.backup_count,
                    "payload_logging_enabled": bool(
                        self.config.logging.log_arguments or self.config.logging.log_responses
                    ),
                    "retention_days": None,
                },
                "configuration_persistence": "startup configuration; restart required",
            }
        )

    @staticmethod
    def _safe_endpoint(value: str) -> str:
        """Drop URL credentials and query values before returning an endpoint summary."""
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname or ""
            if parsed.port:
                hostname = f"{hostname}:{parsed.port}"
            return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))[:512]
        except ValueError:
            return "Configured endpoint"

    def _server_status(self, transport: str) -> str:
        if transport != "http" or self._upstream_reachable is None:
            return "unknown"
        return "healthy" if self._upstream_reachable else "unavailable"

    @staticmethod
    def _safe_audit_event(value: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Return only bounded audit metadata, never payload, error, or finding values."""
        timestamp = value.get("timestamp")
        if not isinstance(timestamp, str) or len(timestamp) > 64:
            return None
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        fields = (
            "agent_id",
            "tenant_id",
            "user_id",
            "server",
            "method",
            "tool",
            "decision",
            "reason_code",
            "correlation_id",
        )
        result: dict[str, Any] = {"timestamp": timestamp}
        for field in fields:
            item = value.get(field)
            if isinstance(item, str):
                result[field] = item[:256]
        request_id = value.get("request_id")
        if isinstance(request_id, (str, int, float)) and not isinstance(request_id, bool):
            result["request_id"] = str(request_id)[:128]
        latency = value.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            result["latency_ms"] = latency
        return result

    @staticmethod
    def _audit_event_matches(event: dict[str, Any], request: Request) -> bool:
        fields = ("agent_id", "tenant_id", "server", "tool", "decision", "method")
        for field in fields:
            requested = request.query_params.get(field)
            if requested and requested.lower() not in str(event.get(field, "")).lower():
                return False
        since = request.query_params.get("since", "")
        until = request.query_params.get("until", "")
        if since and event["timestamp"] < since:
            return False
        if until and event["timestamp"] > until:
            return False
        query = request.query_params.get("q", "").strip().lower()
        if query:
            searchable = " ".join(str(value) for value in event.values()).lower()
            if query not in searchable:
                return False
        return True

    async def _handle_rest_action(self, request: Request) -> Response:
        """Authorize and proxy one statically configured direct REST operation."""
        started = time.monotonic()
        action = request.path_params["action"]
        route = self.config.http.rest_actions.get(action) if self.config.http else None
        if route is None:
            return JSONResponse({"error": "Unknown action"}, status_code=404)
        if len(request.headers.get("mcp-guard-approval-id", "")) > 256:
            return JSONResponse({"error": "Approval ID is too long"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and origin not in self.allowed_origins:
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            return JSONResponse({"error": "Content-Type must be application/json"}, status_code=415)

        token = self._bearer_token(request.headers.get("authorization", ""))
        try:
            with self.tracing.span("mcp.auth.verify", {"transport": "rest_action"}):
                context = await anyio.to_thread.run_sync(
                    self.identity_manager.verify_http_context, token
                )
        except Exception:
            self.metrics.record_authentication_failure()
            self.metrics.record_request("tools/call", "DENY", 0, "AUTHENTICATION_FAILED")
            return JSONResponse({"error": "Authentication failed"}, status_code=401)

        body_bytes = await self._read_limited_request(request)
        if body_bytes is None:
            return JSONResponse(
                {"error": "Request body exceeds the configured limit"}, status_code=413
            )
        try:
            body_text = body_bytes.decode("utf-8")
            arguments = self._parse_json_object(body_text)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return JSONResponse(
                {"error": "Body must be a UTF-8 JSON object without duplicate keys"},
                status_code=400,
            )

        request_id = uuid.uuid4().hex
        call = ToolCallInfo(
            request_id=request_id,
            tool_name=action,
            arguments=arguments,
            server_name=route.server_name,
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            roles=context.roles,
            identity_context=context,
        )

        mcp_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": action, "arguments": arguments},
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        try:
            with self.tracing.span("mcp.dlp.inspect_request", {"mcp.method": "tools/call"}):
                inspected_request = self.tool_controller.dlp_engine.inspect_message(
                    mcp_request,
                    context.agent_id,
                    route.server_name,
                    "request",
                    "tools/call",
                    context,
                )
            inspected_data = json.loads(inspected_request)
            arguments = inspected_data["params"]["arguments"]
            call.arguments = arguments
        except DLPViolationError:
            self.metrics.record_dlp_block()
            self.metrics.record_request(
                "tools/call", "DENY", (time.monotonic() - started) * 1000, "DLP_BLOCKED"
            )
            self.audit_logger.log_access(
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server=route.server_name,
                method="rest/action",
                tool=action,
                decision=DECISION_DENY,
                reason_code="DLP_BLOCKED",
                request_id=request_id,
                correlation_id=request_id,
            )
            return JSONResponse(
                {"error": "Request blocked by data protection policy"}, status_code=403
            )

        with self.tracing.span("mcp.policy.evaluate", {"mcp.method": "tools/call"}):
            decision = self.tool_controller.check_tool_call(call)
        approval_id = request.headers.get("mcp-guard-approval-id", "")
        if decision.decision == "APPROVAL_REQUIRED" and approval_id:
            accepted, reason = self.tool_controller.consume_approval(approval_id, call, context)
            if accepted:
                decision = self.tool_controller.check_tool_call(call, approval_accepted=True)
            else:
                decision.allowed = False
                decision.decision = DECISION_DENY
                decision.reason_code = reason
                decision.reason_message = "Approval is invalid, expired, or already used"
        if decision.decision == "APPROVAL_REQUIRED":
            try:
                approval = self.tool_controller.create_approval(call)
            except OverflowError:
                return JSONResponse({"error": "Approval queue is full"}, status_code=503)
            self.metrics.record_request(
                "tools/call",
                "APPROVAL_REQUIRED",
                (time.monotonic() - started) * 1000,
                "APPROVAL_REQUIRED",
            )
            self.audit_logger.log_access(
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server=route.server_name,
                method="rest/action",
                tool=action,
                decision="APPROVAL_REQUIRED",
                reason_code="APPROVAL_REQUIRED",
                request_id=request_id,
                correlation_id=request_id,
            )
            return JSONResponse(
                {"error": "Human approval required", "approval_id": approval["approval_id"]},
                status_code=202,
            )
        if not decision.allowed:
            self.metrics.record_request(
                "tools/call", "DENY", (time.monotonic() - started) * 1000, decision.reason_code
            )
            self.audit_logger.log_access(
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server=route.server_name,
                method="rest/action",
                tool=action,
                decision=DECISION_DENY,
                reason_code=decision.reason_code,
                request_id=request_id,
                correlation_id=request_id,
            )
            return JSONResponse(
                {"error": "Access denied", "reason": decision.reason_code}, status_code=403
            )

        method = route.method.upper()
        headers = {"Accept": "application/json, text/plain", **route.upstream_headers}
        outgoing: dict[str, Any] = {"headers": headers}
        if method == "GET":
            if any(isinstance(value, (dict, list)) for value in arguments.values()):
                return JSONResponse(
                    {"error": "GET actions accept only scalar arguments"}, status_code=400
                )
            outgoing["params"] = {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in arguments.items()
                if value is not None
            }
        else:
            headers["Content-Type"] = "application/json"
            outgoing["json"] = arguments

        try:
            if not self._http_client:
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.request_timeout), follow_redirects=False
                )
            upstream_request = self._http_client.build_request(method, route.url, **outgoing)
            with self.tracing.span("mcp.upstream.forward", {"mcp.method": "tools/call"}):
                upstream = await self._http_client.send(upstream_request, stream=True)
            try:
                upstream_content = await self._read_limited_response(upstream)
            except _ResponseTooLargeError:
                await upstream.aclose()
                return JSONResponse(
                    {"error": "Upstream response exceeds the configured limit"}, status_code=502
                )
            finally:
                if not upstream.is_closed:
                    await upstream.aclose()
        except httpx.HTTPError:
            self.metrics.record_upstream_failure()
            self.metrics.record_request(
                "tools/call", "DENY", (time.monotonic() - started) * 1000, "UPSTREAM_ERROR"
            )
            self.audit_logger.log_access(
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                server=route.server_name,
                method="rest/action",
                tool=action,
                decision=DECISION_DENY,
                reason_code="UPSTREAM_ERROR",
                request_id=request_id,
                correlation_id=request_id,
            )
            return JSONResponse({"error": "Upstream request failed"}, status_code=502)

        content_type = upstream.headers.get("content-type", "").lower()
        try:
            if upstream.status_code == 204:
                elapsed_ms = (time.monotonic() - started) * 1000
                self.metrics.record_request("tools/call", "ALLOW", elapsed_ms)
                self.audit_logger.log_access(
                    agent_id=context.agent_id,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    server=route.server_name,
                    method="rest/action",
                    tool=action,
                    decision=DECISION_ALLOW,
                    reason_code=decision.reason_code or "POLICY_ALLOWED",
                    request_id=request_id,
                    correlation_id=request_id,
                    latency_ms=elapsed_ms,
                )
                return Response(status_code=204)
            if "json" in content_type:
                upstream_data = json.loads(upstream_content)
                response_wrapper = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"structuredContent": upstream_data},
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                with self.tracing.span("mcp.dlp.inspect_response", {"mcp.method": "tools/call"}):
                    inspected_response = self.tool_controller.dlp_engine.inspect_message(
                        response_wrapper,
                        context.agent_id,
                        route.server_name,
                        "response",
                        "tools/call",
                        context,
                    )
                response_data = json.loads(inspected_response)["result"]["structuredContent"]
                result: Response = JSONResponse(response_data, status_code=upstream.status_code)
            else:
                response_text = upstream_content.decode("utf-8")
                safe_text = self.tool_controller.dlp_engine.inspect_message(
                    response_text,
                    context.agent_id,
                    route.server_name,
                    "response",
                    "tools/call",
                    context,
                )
                result = Response(
                    safe_text,
                    status_code=upstream.status_code,
                    media_type="text/plain",
                )
        except (DLPViolationError, UnicodeDecodeError, json.JSONDecodeError):
            self.metrics.record_dlp_block()
            self.metrics.record_request(
                "tools/call", "DENY", (time.monotonic() - started) * 1000, "DLP_BLOCKED"
            )
            return JSONResponse(
                {"error": "Upstream response blocked by data protection policy"}, status_code=502
            )

        elapsed_ms = (time.monotonic() - started) * 1000
        self.metrics.record_request("tools/call", "ALLOW", elapsed_ms, decision.reason_code)
        self.audit_logger.log_access(
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            server=route.server_name,
            method="rest/action",
            tool=action,
            decision=DECISION_ALLOW,
            reason_code=decision.reason_code or "POLICY_ALLOWED",
            request_id=request_id,
            correlation_id=request_id,
            latency_ms=elapsed_ms,
        )
        return result

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, Any]:
        """Parse a JSON object and reject duplicate keys and nonstandard numbers."""

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, value in pairs:
                if key in parsed:
                    raise ValueError("duplicate JSON key")
                parsed[key] = value
            return parsed

        def reject_constant(value: str) -> None:
            raise ValueError(f"invalid JSON constant: {value}")

        value = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    async def _list_approvals(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        state = request.query_params.get("state", "")
        if state and state not in {"pending", "approved", "rejected", "expired", "consumed"}:
            return JSONResponse({"error": "Invalid approval state"}, status_code=400)
        return JSONResponse(
            {"approvals": self.tool_controller.approval_service.list_requests(state)}
        )

    async def _decide_approval(self, request: Request) -> JSONResponse:
        start_time = time.monotonic()
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        try:
            body = await request.json()
        except Exception:
            self.metrics.record_request(
                "other",
                "DENY",
                (time.monotonic() - start_time) * 1000,
                "INVALID_ADMIN_REQUEST",
            )
            return JSONResponse({"error": "Expected a JSON request body"}, status_code=400)
        decision = body.get("decision") if isinstance(body, dict) else None
        if decision not in {"approve", "reject"}:
            return JSONResponse(
                {"error": "decision must be 'approve' or 'reject'"}, status_code=400
            )
        approval_id = request.path_params["approval_id"]
        try:
            record = self.tool_controller.approval_service.decide(
                approval_id, admin[0], decision == "approve"
            )
        except KeyError:
            return JSONResponse({"error": "Approval request not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        self.audit_logger.log_access(
            agent_id=admin[0],
            server=record["server"],
            method="admin/approvals/decision",
            decision=decision.upper(),
            reason_code="HUMAN_APPROVAL_DECISION",
            tool=record["tool"],
        )
        return JSONResponse(record)

    async def _get_policy(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        version, policy = self.tool_controller.policy_manager.snapshot()
        return JSONResponse(
            {
                "version": version,
                "policy": policy.model_dump(mode="json", by_alias=True),
                "history": self.tool_controller.policy_manager.history(),
            }
        )

    async def _update_policy(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        try:
            body = await request.json()
            candidate_data = body.get("policy", body) if isinstance(body, dict) else body
            candidate = PolicyConfig.model_validate(candidate_data)
            version = self.tool_controller.policy_manager.update(candidate, admin[0])
        except (ValueError, TypeError, ConfigurationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception:
            logger.exception("Runtime policy update was rejected")
            return JSONResponse({"error": "Policy validation failed"}, status_code=400)
        self.audit_logger.log_access(
            agent_id=admin[0],
            server="",
            method="admin/policy/update",
            decision="UPDATED",
            reason_code=f"POLICY_VERSION_{version}",
        )
        return JSONResponse({"version": version, "status": "active"})

    async def _rollback_policy(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        version = int(request.path_params["version"])
        try:
            active_version = self.tool_controller.policy_manager.rollback(version, admin[0])
        except ConfigurationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        self.audit_logger.log_access(
            agent_id=admin[0],
            server="",
            method="admin/policy/rollback",
            decision="ROLLED_BACK",
            reason_code=f"POLICY_ROLLBACK_{version}_TO_{active_version}",
        )
        return JSONResponse({"version": active_version, "rolled_back_to": version})

    async def _revoke_token(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Expected a JSON request body"}, status_code=400)
        if not isinstance(body, dict) or ("token_hash" in body) == ("jti" in body):
            return JSONResponse(
                {"error": "Provide exactly one of token_hash or jti"}, status_code=400
            )
        try:
            if isinstance(body.get("token_hash"), str):
                self.identity_manager.revoke_token_hash(body["token_hash"])
                reason = "TOKEN_HASH_REVOKED"
            elif isinstance(body.get("jti"), str):
                self.identity_manager.revoke_jti(body["jti"])
                reason = "JWT_JTI_REVOKED"
            else:
                return JSONResponse({"error": "Revocation value must be a string"}, status_code=400)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        self.audit_logger.log_access(
            agent_id=admin[0],
            server="",
            method="admin/tokens/revoke",
            decision="REVOKED",
            reason_code=reason,
        )
        return JSONResponse({"status": "revoked"})

    async def _rotate_token(self, request: Request) -> JSONResponse:
        admin = self._authenticate_admin(request)
        if admin is None:
            return self._admin_unauthorized()
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Expected a JSON request body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Expected a JSON object"}, status_code=400)
        old_hash = body.get("old_token_hash")
        new_hash = body.get("new_token_hash")
        if not isinstance(old_hash, str) or not isinstance(new_hash, str):
            return JSONResponse(
                {"error": "old_token_hash and new_token_hash are required"}, status_code=400
            )
        try:
            self.identity_manager.rotate_token_hash(old_hash, new_hash)
        except KeyError:
            return JSONResponse({"error": "Old token hash is not active"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        self.audit_logger.log_access(
            agent_id=admin[0],
            server="",
            method="admin/tokens/rotate",
            decision="ROTATED",
            reason_code="TOKEN_ROTATED",
        )
        return JSONResponse({"status": "rotated"})

    def _authenticate_admin(self, request: Request) -> Optional[tuple[str, list[str]]]:
        token = self._bearer_token(request.headers.get("authorization", ""))
        try:
            return self.identity_manager.verify_admin_token(token)
        except Exception:
            self.metrics.record_authentication_failure()
            self.audit_logger.log_access(
                agent_id="",
                server="",
                method="admin/authentication",
                decision=DECISION_DENY,
                reason_code="ADMIN_AUTHENTICATION_FAILED",
            )
            return None

    @staticmethod
    def _admin_unauthorized() -> JSONResponse:
        return JSONResponse({"error": "Administrator authentication required"}, status_code=401)

    async def _handle_mcp(self, request: Request) -> Response:
        """Authenticate, inspect, and forward one MCP HTTP request."""
        start_time = time.monotonic()

        origin = request.headers.get("origin")
        if origin and origin not in self.allowed_origins:
            logger.warning("Rejected request from disallowed origin")
            return self._http_error(403, "Origin not allowed")

        token = self._bearer_token(request.headers.get("authorization", ""))
        try:
            with self.tracing.span("mcp.auth.verify", {"transport": "mcp_http"}):
                identity_context = await anyio.to_thread.run_sync(
                    self.identity_manager.verify_http_context, token
                )
            agent = self.identity_manager.get_agent(identity_context.agent_id)
            if agent is None:
                raise ValueError("Authenticated agent is unavailable")
        except Exception:
            self.metrics.record_authentication_failure()
            self.audit_logger.log_access(
                agent_id="",
                server="",
                method="",
                decision=DECISION_DENY,
                reason_code="AUTHENTICATION_FAILED",
            )
            return self._http_error(401, "Authentication failed")

        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return self._http_error(415, "Content-Type must be application/json")

        if not self._accepts_mcp_response(request.headers.get("accept", "")):
            return self._http_error(
                406, "Accept must include application/json and text/event-stream"
            )

        body = await self._read_limited_request(request)
        if body is None:
            return self._http_error(413, "Request too large")
        try:
            raw = body.decode("utf-8")
        except UnicodeDecodeError:
            return self._http_error(400, "Request body must be UTF-8")

        parsed = parse_message_permissive(raw)
        approval_id = request.headers.get("mcp-guard-approval-id")
        if approval_id and len(approval_id) > 256:
            return self._http_error(400, "Approval ID is too long")
        protocol_error = self._validate_protocol_headers(request, parsed, agent.id)
        if protocol_error is not None:
            code, message = protocol_error
            request_id = parsed.id if parsed and parsed.has_id else None
            error_data = None
            if code == -32022:
                requested = request.headers.get("mcp-protocol-version")
                if parsed and isinstance(parsed.params, dict):
                    metadata = parsed.params.get("_meta", {})
                    if isinstance(metadata, dict):
                        requested = metadata.get(PROTOCOL_VERSION_KEY, requested)
                error_data = {
                    "supported": SUPPORTED_PROTOCOL_VERSIONS,
                    "requested": requested,
                }
            return JSONResponse(
                json.loads(create_error_response(request_id, code, message, error_data)),
                status_code=400,
            )

        server_name = self._server_name()
        agent_id = agent.id
        with self.tracing.span("mcp.request.authorize_and_inspect"):
            forward_message, error_response = self.message_router.process_request(
                raw, agent_id, server_name, identity_context, approval_id
            )
        if error_response:
            tool_name, arguments = self._tool_call_details(parsed)
            try:
                error_data = json.loads(error_response).get("error", {}).get("data", {})
                raw_reason = error_data.get("reason", "")
                reason_code = raw_reason if isinstance(raw_reason, str) else ""
            except (json.JSONDecodeError, AttributeError):
                reason_code = ""
            if not reason_code:
                reason_code = (
                    "DLP_BLOCKED" if "data-protection" in error_response else "POLICY_DENIED"
                )
            self.metrics.record_request(
                (parsed.method or "") if parsed else "",
                "APPROVAL_REQUIRED" if reason_code == "APPROVAL_REQUIRED" else "DENY",
                (time.monotonic() - start_time) * 1000,
                reason_code,
            )
            if parsed and parsed.is_request:
                params = parsed.params or {}
                self.audit_logger.log_access(
                    agent_id=agent_id,
                    server=server_name,
                    method=parsed.method or "",
                    decision=DECISION_DENY,
                    reason_code=reason_code,
                    request_id=parsed.id,
                    tool=tool_name,
                    latency_ms=(time.monotonic() - start_time) * 1000,
                    arguments=arguments,
                    tenant_id=identity_context.tenant_id,
                    user_id=identity_context.user_id,
                    resource=(params.get("uri") if isinstance(params.get("uri"), str) else None),
                    prompt=(
                        params.get("name")
                        if parsed.method == "prompts/get" and isinstance(params.get("name"), str)
                        else None
                    ),
                    correlation_id=str(parsed.id),
                )
            status_code = 200 if parsed and parsed.is_request else 400
            return Response(error_response, status_code=status_code, media_type="application/json")

        if forward_message is None:
            return self._http_error(500, "Request could not be processed")
        if not self.upstream_url:
            self.metrics.record_upstream_failure()
            return self._http_error(502, "No upstream server is configured")

        forwarded_parsed = parse_message_permissive(forward_message)
        forward_headers = self._upstream_request_headers(request, forwarded_parsed, agent.id)
        try:
            with self.tracing.span(
                "mcp.upstream.forward",
                {"mcp.method": parsed.method if parsed and parsed.method else "other"},
            ):
                upstream_response = await self._forward_to_upstream(
                    forward_message, forward_headers
                )
        except httpx.TimeoutException:
            self.metrics.record_upstream_failure()
            self._upstream_reachable = False
            logger.warning("Upstream request timed out")
            return self._http_error(504, "Upstream request timed out")
        except httpx.HTTPError as e:
            self.metrics.record_upstream_failure()
            self._upstream_reachable = False
            logger.warning("Upstream request failed: %s", e)
            return self._http_error(502, "Upstream request failed")

        method = parsed.method if parsed and parsed.is_request else None
        self._upstream_reachable = True
        if parsed and parsed.is_request:
            self.metrics.record_request(
                method or "",
                "ALLOW",
                (time.monotonic() - start_time) * 1000,
            )
        if parsed and parsed.is_request:
            tool_name, arguments = self._tool_call_details(parsed)
            params = parsed.params or {}
            self.audit_logger.log_access(
                agent_id=agent_id,
                server=server_name,
                method=parsed.method or "",
                decision=DECISION_ALLOW,
                request_id=parsed.id,
                tool=tool_name,
                latency_ms=(time.monotonic() - start_time) * 1000,
                arguments=(
                    self._forwarded_arguments(forward_message, arguments)
                    if parsed.method == METHOD_TOOLS_CALL
                    else arguments
                ),
                tenant_id=identity_context.tenant_id,
                user_id=identity_context.user_id,
                resource=(params.get("uri") if isinstance(params.get("uri"), str) else None),
                prompt=(
                    params.get("name")
                    if parsed.method == "prompts/get" and isinstance(params.get("name"), str)
                    else None
                ),
                correlation_id=str(parsed.id),
            )

        upstream_content_type = upstream_response.headers.get("content-type", "")
        response_headers = self._downstream_response_headers(upstream_response.headers)

        if parsed and parsed.is_notification and upstream_response.status_code == 202:
            await upstream_response.aclose()
            return Response(content=b"", status_code=202, headers=response_headers)

        if (
            "text/event-stream" not in upstream_content_type.lower()
            and "json" not in upstream_content_type.lower()
        ):
            await upstream_response.aclose()
            return self._http_error(502, "Upstream returned an unsupported content type")

        if "text/event-stream" in upstream_content_type.lower():

            async def stream_events() -> Any:
                try:
                    async for event in self._inspect_sse_stream(
                        upstream_response,
                        agent_id,
                        server_name,
                        method,
                        parsed.id if parsed and parsed.is_request else None,
                        identity_context,
                    ):
                        yield event
                except httpx.TimeoutException:
                    logger.warning("Timed out while streaming the upstream response")
                    yield _sse_data(
                        create_error_response(
                            parsed.id if parsed and parsed.is_request else None,
                            -32001,
                            "Upstream response timed out",
                        )
                    )
                finally:
                    await upstream_response.aclose()

            response_headers.setdefault("Cache-Control", "no-cache")
            response_headers.setdefault("X-Accel-Buffering", "no")
            return StreamingResponse(
                stream_events(),
                status_code=upstream_response.status_code,
                media_type="text/event-stream",
                headers=response_headers,
            )

        try:
            upstream_body = await self._read_limited_response(upstream_response)
        except _ResponseTooLargeError:
            await upstream_response.aclose()
            return Response(
                create_error_response(
                    parsed.id if parsed and parsed.is_request else None,
                    -32001,
                    "Upstream response exceeds the configured size limit",
                ),
                status_code=502,
                media_type="application/json",
            )
        finally:
            if not upstream_response.is_closed:
                await upstream_response.aclose()

        try:
            response_text = upstream_body.decode("utf-8")
        except UnicodeDecodeError:
            return self._http_error(502, "Upstream response is not valid UTF-8")

        if not response_text and parsed and parsed.is_notification:
            return Response(
                content=b"",
                status_code=upstream_response.status_code,
                headers=response_headers,
            )

        with self.tracing.span(
            "mcp.response.inspect",
            {"mcp.method": method if method else "other"},
        ):
            processed, transformation = self.message_router.process_response_with_decision(
                response_text,
                agent_id,
                server_name,
                method,
                identity_context,
                parsed.id if parsed and parsed.is_request else None,
            )
        if method == "tools/list":
            self._cache_tool_header_parameters(processed, agent_id)
        if transformation:
            if transformation == "DLP_BLOCKED":
                self.metrics.record_dlp_block()
            processed_data = self._json_for_optional_audit(processed)
            self.audit_logger.log_access(
                agent_id=agent_id,
                server=server_name,
                method=method or "",
                decision=(DECISION_DENY if transformation == "DLP_BLOCKED" else DECISION_REDACT),
                reason_code=transformation,
                request_id=parsed.id if parsed and parsed.is_request else None,
                response=processed_data,
            )

        if self.config.logging.log_responses:
            self.audit_logger.log_access(
                agent_id=agent_id,
                server=server_name,
                method=method or "",
                decision="OBSERVED",
                request_id=parsed.id if parsed and parsed.is_request else None,
                response=self._json_for_optional_audit(processed),
            )

        response_headers["Content-Type"] = upstream_content_type or "application/json"
        return Response(
            content=processed,
            status_code=upstream_response.status_code,
            headers=response_headers,
        )

    def _validate_protocol_headers(
        self,
        request: Request,
        parsed: Optional[JSONRPCMessage],
        agent_id: str = "",
    ) -> Optional[tuple[int, str]]:
        """Check the 2026 per-request envelope and its mirrored HTTP headers."""
        if parsed is None:
            return None  # The message router returns the JSON-RPC parse error.

        params = parsed.params or {}
        metadata = params.get("_meta") if isinstance(params, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        protocol_version = metadata.get(PROTOCOL_VERSION_KEY)
        header_version = request.headers.get("mcp-protocol-version")

        if protocol_version is not None and protocol_version != CURRENT_PROTOCOL_VERSION:
            return (
                -32022,
                f"Unsupported protocol version; supported: {', '.join(SUPPORTED_MODERN_VERSIONS)}",
            )

        if protocol_version is None and header_version == CURRENT_PROTOCOL_VERSION:
            return -32020, "MCP-Protocol-Version header does not match request metadata"

        if protocol_version == CURRENT_PROTOCOL_VERSION:
            if header_version != protocol_version:
                return -32020, "MCP-Protocol-Version header does not match request metadata"
            capabilities = metadata.get(CLIENT_CAPABILITIES_KEY)
            client_info = metadata.get(CLIENT_INFO_KEY)
            if not isinstance(capabilities, dict):
                return -32021, "Request is missing client capabilities metadata"
            if client_info is not None and (
                not isinstance(client_info, dict)
                or not isinstance(client_info.get("name"), str)
                or not isinstance(client_info.get("version"), str)
            ):
                return -32602, "Invalid client identity metadata"

            if request.headers.get("mcp-method") != parsed.method:
                return -32020, "Mcp-Method header does not match the request body"
            expected_name: Optional[str] = None
            if parsed.method == "tools/call":
                name = params.get("name")
                if isinstance(name, str):
                    expected_name = name
            elif parsed.method == "resources/read":
                uri = params.get("uri")
                if isinstance(uri, str):
                    expected_name = uri
            elif parsed.method == "prompts/get":
                name = params.get("name")
                if isinstance(name, str):
                    expected_name = name
            elif parsed.method in {"tasks/get", "tasks/update", "tasks/cancel"}:
                task_id = params.get("taskId")
                if isinstance(task_id, str):
                    expected_name = task_id
            if expected_name is not None:
                header_name = self._decode_mcp_header_value(request.headers.get("mcp-name", ""))
                if header_name != expected_name:
                    return -32020, "Mcp-Name header does not match the request body"

            parameter_error = self._validate_parameter_headers(request, parsed, agent_id)
            if parameter_error:
                return -32020, parameter_error

            if parsed.is_notification:
                return -32600, "Notifications are not supported over the modern HTTP transport"
            return None

        # Handshake-era requests are forwarded unchanged. The 2026 transport
        # removed sessions; the 2025 Streamable HTTP session ID is passed
        # through as an opaque value, and no legacy HTTP+SSE GET endpoint exists.
        if header_version and header_version not in SUPPORTED_LEGACY_HTTP_VERSIONS:
            return -32022, f"Unsupported protocol version: {header_version}"
        return None

    def _server_name(self) -> str:
        """Resolve the policy server identifier from trusted configuration."""
        if self.upstream_url:
            for name, upstream in self.config.upstreams.items():
                if upstream.url == self.upstream_url:
                    return name
        return "http_upstream"

    def _upstream_request_headers(
        self,
        request: Request,
        parsed: Optional[JSONRPCMessage],
        agent_id: str = "",
    ) -> dict[str, str]:
        """Forward only MCP transport headers and administrator-set headers."""
        headers = dict(self.upstream_headers)
        headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
        )
        for name, value in request.headers.items():
            lowered = name.lower()
            if lowered in FORWARDED_REQUEST_HEADERS:
                headers[name] = value

        if parsed:
            params = parsed.params or {}
            metadata = params.get("_meta") if isinstance(params, dict) else None
            if (
                isinstance(metadata, dict)
                and metadata.get(PROTOCOL_VERSION_KEY) == CURRENT_PROTOCOL_VERSION
            ):
                self._set_header(headers, "MCP-Protocol-Version", CURRENT_PROTOCOL_VERSION)
                self._set_header(headers, "Mcp-Method", parsed.method or "")
                if parsed.method == "tools/call" and isinstance(params.get("name"), str):
                    self._set_header(
                        headers, "Mcp-Name", self._encode_mcp_header_value(params["name"])
                    )
                elif parsed.method == "resources/read" and isinstance(params.get("uri"), str):
                    self._set_header(
                        headers, "Mcp-Name", self._encode_mcp_header_value(params["uri"])
                    )
                elif parsed.method == "prompts/get" and isinstance(params.get("name"), str):
                    self._set_header(
                        headers, "Mcp-Name", self._encode_mcp_header_value(params["name"])
                    )
                if parsed.method == "tools/call":
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})
                    if isinstance(tool_name, str) and isinstance(arguments, dict):
                        mapping = self._tool_header_parameters.get((agent_id, tool_name), {})
                        for argument_name, header_name in mapping.items():
                            if argument_name in arguments:
                                header_value = self._header_parameter_value(
                                    arguments[argument_name]
                                )
                                if header_value is not None:
                                    self._set_header(
                                        headers,
                                        f"Mcp-Param-{header_name}",
                                        self._encode_mcp_header_value(header_value),
                                    )

        # Administrator-owned authentication values are trusted; caller
        # Authorization, Cookie, Host, and hop-by-hop headers are never copied.
        return headers

    def _validate_parameter_headers(
        self, request: Request, parsed: JSONRPCMessage, agent_id: str
    ) -> Optional[str]:
        """Validate modern x-mcp-header mirrors against the JSON arguments."""
        received = {
            name.lower(): value
            for name, value in request.headers.items()
            if name.lower().startswith("mcp-param-")
        }
        params = parsed.params or {}
        if parsed.method != "tools/call":
            return "Mcp-Param headers are only valid for tools/call" if received else None
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            return "Mcp-Param headers require valid tool arguments"
        mapping = self._tool_header_parameters.get((agent_id, tool_name), {})
        if not received and not any(name in arguments for name in mapping):
            return None
        expected_headers: set[str] = set()
        for argument_name, header_name in mapping.items():
            if argument_name not in arguments or arguments[argument_name] is None:
                continue
            header_key = f"mcp-param-{header_name}".lower()
            expected_headers.add(header_key)
            expected_value = self._header_parameter_value(arguments[argument_name])
            if expected_value is None:
                return f"Tool argument '{argument_name}' cannot be mirrored to an HTTP header"
            received_value = received.get(header_key)
            if received_value is None:
                return f"Missing required {header_key} header"
            decoded_value = self._decode_mcp_header_value(received_value)
            if decoded_value != expected_value:
                return f"{header_key} header does not match the request body"
        if set(received) != expected_headers:
            return "Mcp-Param headers do not match the declared tool parameters"
        return None

    def _cache_tool_header_parameters(self, raw: str, agent_id: str) -> None:
        """Cache only valid, non-reserved header annotations from visible tools."""
        try:
            data = json.loads(raw)
            tools = data.get("result", {}).get("tools", [])
        except (json.JSONDecodeError, AttributeError, TypeError):
            return
        if not isinstance(tools, list):
            return
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                continue
            schema = tool.get("inputSchema", tool.get("input_schema", {}))
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if not isinstance(properties, dict):
                continue
            mapping: dict[str, str] = {}
            used_headers: set[str] = set()
            invalid = False
            for argument_name, definition in properties.items():
                if not isinstance(definition, dict):
                    continue
                header_name = definition.get("x-mcp-header")
                if header_name is None:
                    continue
                if (
                    not isinstance(argument_name, str)
                    or not isinstance(header_name, str)
                    or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header_name)
                    or header_name.lower()
                    in {
                        "authorization",
                        "proxy-authorization",
                        "cookie",
                        "host",
                        "origin",
                        "content-type",
                        "accept",
                        "connection",
                        "transfer-encoding",
                        "mcp-protocol-version",
                        "mcp-method",
                        "mcp-name",
                        "mcp-session-id",
                    }
                    or definition.get("type") not in {"string", "integer", "boolean"}
                    or header_name.lower() in used_headers
                ):
                    invalid = True
                    break
                mapping[argument_name] = header_name
                used_headers.add(header_name.lower())
            if not invalid:
                self._tool_header_parameters[(agent_id, tool["name"])] = mapping

    @staticmethod
    def _header_parameter_value(value: Any) -> Optional[str]:
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        return None

    @staticmethod
    def _set_header(headers: dict[str, str], name: str, value: str) -> None:
        """Replace a header without creating case-variant duplicates."""
        for key in list(headers):
            if key.lower() == name.lower():
                del headers[key]
        headers[name] = value

    @staticmethod
    def _encode_mcp_header_value(value: str) -> str:
        """Encode a name that cannot be safely represented as an HTTP header value."""
        safe_ascii = all(0x21 <= ord(char) <= 0x7E or char in " \t" for char in value)
        padded = value.startswith((" ", "\t")) or value.endswith((" ", "\t"))
        sentinel = value.startswith("=?base64?") and value.endswith("?=")
        if safe_ascii and not padded and not sentinel:
            return value
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return f"=?base64?{encoded}?="

    @staticmethod
    def _decode_mcp_header_value(value: str) -> Optional[str]:
        """Decode MCP's sentinel-wrapped base64 header representation."""
        prefix = "=?base64?"
        suffix = "?="
        if value.startswith(prefix) and value.endswith(suffix):
            encoded = value[len(prefix) : -len(suffix)]
            try:
                return base64.b64decode(encoded, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return None
        safe_ascii = all(0x21 <= ord(char) <= 0x7E or char in " \t" for char in value)
        padded = value.startswith((" ", "\t")) or value.endswith((" ", "\t"))
        if not safe_ascii or padded:
            return None
        return value

    def _downstream_response_headers(self, upstream_headers: httpx.Headers) -> dict[str, str]:
        """Preserve only protocol response headers, not upstream hop metadata."""
        return {
            name: value
            for name, value in upstream_headers.items()
            if name.lower() in RESPONSE_HEADERS
        }

    async def _read_limited_request(self, request: Request) -> Optional[bytes]:
        """Read request chunks without allowing an unbounded body allocation."""
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return None
            if length < 0 or length > self.max_message_size:
                return None

        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > self.max_message_size:
                    return None
                body.extend(chunk)
        except ClientDisconnect:
            return None
        return bytes(body)

    async def _read_limited_response(self, response: httpx.Response) -> bytes:
        """Buffer an ordinary JSON response up to the configured limit."""
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > self.max_message_size:
                raise _ResponseTooLargeError
            body.extend(chunk)
        return bytes(body)

    async def _inspect_sse_stream(
        self,
        response: httpx.Response,
        agent_id: str,
        server_name: str,
        method: Optional[str],
        request_id: Any,
        context: Optional[IdentityContext] = None,
    ) -> Any:
        """Transform complete SSE events while bounding each event in memory."""
        pending = bytearray()
        async for chunk in response.aiter_bytes():
            pending.extend(chunk)
            if len(pending) > self.max_message_size and not _find_sse_boundary(pending):
                yield _sse_data(create_error_response(request_id, -32001, "SSE event too large"))
                return
            while True:
                boundary = _find_sse_boundary(pending)
                if boundary is None:
                    break
                offset, width = boundary
                event_bytes = bytes(pending[:offset])
                del pending[: offset + width]
                if len(event_bytes) > self.max_message_size:
                    yield _sse_data(
                        create_error_response(request_id, -32001, "SSE event too large")
                    )
                    return
                event = event_bytes.decode("utf-8", errors="replace")
                processed = self._inspect_sse_event(
                    event, agent_id, server_name, method, context, request_id
                )
                yield (processed + "\r\n\r\n").encode("utf-8")
        if pending:
            if len(pending) > self.max_message_size:
                yield _sse_data(create_error_response(request_id, -32001, "SSE event too large"))
                return
            event = pending.decode("utf-8", errors="replace")
            processed = self._inspect_sse_event(
                event, agent_id, server_name, method, context, request_id
            )
            yield processed.encode("utf-8")

    def _inspect_sse_event(
        self,
        event: str,
        agent_id: str,
        server_name: str,
        method: Optional[str],
        context: Optional[IdentityContext] = None,
        request_id: Any = None,
    ) -> str:
        """Preserve SSE fields while applying inspection to its data payload."""
        lines = event.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        output: list[str] = []
        data_lines: list[str] = []
        data_inserted = False
        for line in lines:
            if line.startswith("data:"):
                if not data_inserted:
                    data_inserted = True
                    data_lines.append(line[5:].removeprefix(" "))
                else:
                    data_lines.append(line[5:].removeprefix(" "))
                continue
            output.append(line)
        if data_lines:
            data = "\n".join(data_lines)
            processed, reason_code = self.message_router.process_response_with_decision(
                data, agent_id, server_name, method, context, request_id
            )
            if method == "tools/list":
                self._cache_tool_header_parameters(processed, agent_id)
            if reason_code:
                parsed = parse_message_permissive(data)
                self.audit_logger.log_access(
                    agent_id=agent_id,
                    server=server_name,
                    method=method or "",
                    decision=DECISION_DENY if reason_code == "DLP_BLOCKED" else DECISION_REDACT,
                    reason_code=reason_code,
                    request_id=parsed.id if parsed and parsed.has_id else None,
                    response=self._json_for_optional_audit(processed),
                )
            if processed:
                output.append(f"data: {processed}")
            else:
                return ""
        return "\r\n".join(output)

    async def _forward_to_upstream(
        self,
        message: str,
        headers: dict[str, str],
    ) -> httpx.Response:
        """Send one request without forwarding caller authentication implicitly."""
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.request_timeout),
                follow_redirects=False,
            )
        upstream_request = self._http_client.build_request(
            "POST",
            self.upstream_url,
            content=message,
            headers=headers,
        )
        return await self._http_client.send(upstream_request, stream=True)

    @staticmethod
    def _bearer_token(header: str) -> str:
        """Parse an HTTP Bearer scheme without accepting other auth schemes."""
        scheme, separator, credentials = header.partition(" ")
        return credentials.strip() if separator and scheme.lower() == "bearer" else ""

    @staticmethod
    def _accepts_mcp_response(accept: str) -> bool:
        media_types = {item.split(";", 1)[0].strip().lower() for item in accept.split(",")}
        return {"application/json", "text/event-stream"}.issubset(media_types)

    @staticmethod
    def _http_error(status_code: int, message: str) -> JSONResponse:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": message}},
            status_code=status_code,
        )

    @staticmethod
    def _tool_call_details(
        message: Optional[JSONRPCMessage],
    ) -> tuple[str, Optional[dict[str, Any]]]:
        if not message or not isinstance(message.params, dict):
            return "", None
        name = message.params.get("name")
        arguments = message.params.get("arguments", {})
        return (
            name if isinstance(name, str) else "",
            arguments if isinstance(arguments, dict) else None,
        )

    @staticmethod
    def _forwarded_arguments(
        message: str,
        original: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        parsed = parse_message_permissive(message)
        if parsed and isinstance(parsed.params, dict):
            forwarded = parsed.params.get("arguments")
            if isinstance(forwarded, dict):
                return forwarded
        return original

    @staticmethod
    def _json_for_optional_audit(value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value


class _ResponseTooLargeError(Exception):
    """Raised when a buffered JSON response exceeds the configured limit."""


def _find_sse_boundary(data: bytearray) -> Optional[tuple[int, int]]:
    """Return the earliest blank-line separator in an SSE byte buffer."""
    matches = [
        (data.find(b"\r\n\r\n"), 4),
        (data.find(b"\n\n"), 2),
        (data.find(b"\r\r"), 2),
    ]
    matches = [match for match in matches if match[0] >= 0]
    return min(matches, key=lambda match: match[0]) if matches else None


def _sse_data(message: str) -> bytes:
    return f"data: {message}\r\n\r\n".encode()
