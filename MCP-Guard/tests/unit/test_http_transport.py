"""HTTP transport integration tests using in-process ASGI and upstream clients."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx
import pytest

from mcp_guard.core.models import (
    AdminCredential,
    DLPMode,
    DLPPattern,
    HTTPTransportConfig,
    PolicyAction,
    RESTActionConfig,
    ToolPolicy,
    UpstreamConfig,
)
from mcp_guard.transports.http import CURRENT_PROTOCOL_VERSION, HTTPTransport


def _modern_request(
    method: str, request_id: int, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": CURRENT_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1"},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": request_params}


def _transport(sample_config, upstream_handler) -> HTTPTransport:
    token = "client-token"
    sample_config.transport = "http"
    sample_config.http = HTTPTransportConfig(upstream_url="https://upstream.example/mcp")
    sample_config.identity.agents["support_agent"].api_key_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()
    sample_config.upstreams["customer_database"] = UpstreamConfig(
        name="customer_database", url=sample_config.http.upstream_url
    )
    transport = HTTPTransport(sample_config)
    transport._http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
    return transport


async def _send(
    transport: HTTPTransport,
    message: dict[str, Any],
    method_name: str,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    app_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        metadata = message.get("params", {}).get("_meta", {})
        protocol_version = metadata.get(
            "io.modelcontextprotocol/protocolVersion", CURRENT_PROTOCOL_VERSION
        )
        headers = {
            "Authorization": "Bearer client-token",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": protocol_version,
            "Mcp-Method": method_name,
        }
        if method_name == "tools/call":
            headers["Mcp-Name"] = HTTPTransport._encode_mcp_header_value(message["params"]["name"])
        headers.update(extra_headers or {})
        return await app_client.post("/mcp", headers=headers, json=message)
    finally:
        await app_client.aclose()


async def _send_rest_action(
    transport: HTTPTransport,
    action: str,
    arguments: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    app_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        headers = {
            "Authorization": "Bearer client-token",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        return await app_client.post(f"/api/v1/actions/{action}", headers=headers, json=arguments)
    finally:
        await app_client.aclose()


@pytest.mark.asyncio
async def test_modern_request_is_forwarded_without_client_credentials(sample_config) -> None:
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        body = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        return httpx.Response(200, json=body)

    transport = _transport(sample_config, upstream)
    try:
        response = await _send(transport, _modern_request("initialize", 1), "initialize")
        assert response.status_code == 200
        assert response.json()["result"] == {"ok": True}
        assert len(received) == 1
        assert received[0].headers["mcp-protocol-version"] == CURRENT_PROTOCOL_VERSION
        assert received[0].headers["mcp-method"] == "initialize"
        assert "authorization" not in received[0].headers
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_modern_header_mismatch_is_rejected_before_upstream(sample_config) -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {}})

    transport = _transport(sample_config, upstream)
    try:
        response = await _send(transport, _modern_request("ping", 2), "initialize")
        assert response.status_code == 400
        assert "does not match" in response.json()["error"]["message"]
        assert calls == 0
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_redacted_argument_and_mcp_param_header_stay_consistent(sample_config) -> None:
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "get_customer",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "email": {
                                            "type": "string",
                                            "x-mcp-header": "Customer-Email",
                                        }
                                    },
                                },
                            }
                        ]
                    },
                },
            )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}
        )

    transport = _transport(sample_config, upstream)
    try:
        listed = await _send(transport, _modern_request("tools/list", 1), "tools/list")
        assert listed.status_code == 200
        request = _modern_request(
            "tools/call",
            2,
            {"name": "get_customer", "arguments": {"email": "customer@example.com"}},
        )
        response = await _send(
            transport,
            request,
            "tools/call",
            {"Mcp-Param-Customer-Email": "customer@example.com"},
        )
        assert response.status_code == 200
        forwarded = json.loads(received[-1].content)
        assert forwarded["params"]["arguments"]["email"] == "[REDACTED_EMAIL]"
        assert received[-1].headers["mcp-param-customer-email"] == "[REDACTED_EMAIL]"

        mismatched = _modern_request(
            "tools/call",
            3,
            {"name": "get_customer", "arguments": {"email": "another@example.com"}},
        )
        rejected = await _send(
            transport,
            mismatched,
            "tools/call",
            {"Mcp-Param-Customer-Email": "wrong@example.com"},
        )
        assert rejected.status_code == 400
        assert len(received) == 2
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_direct_rest_action_reuses_identity_policy_and_dlp(sample_config) -> None:
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        assert request.headers["authorization"] == "Bearer upstream-only"
        return httpx.Response(
            200,
            json={
                "submitted": json.loads(request.content),
                "contact": "alice@example.com",
            },
        )

    transport = _transport(sample_config, upstream)
    sample_config.http.rest_actions["get_customer"] = RESTActionConfig(
        server_name="customer_database",
        url="https://rest.example/customers/lookup",
        method="POST",
        upstream_headers={"Authorization": "Bearer upstream-only"},
    )
    try:
        response = await _send_rest_action(
            transport,
            "get_customer",
            {"customer_id": "C001", "email": "customer@example.com"},
        )
        assert response.status_code == 200
        assert len(received) == 1
        sent = json.loads(received[0].content)
        assert sent["email"] == "[REDACTED_EMAIL]"
        assert "client-token" not in received[0].headers["authorization"]
        result = response.json()
        assert result["submitted"]["email"] == "[REDACTED_EMAIL]"
        assert result["contact"] == "[REDACTED_EMAIL]"
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_direct_rest_denial_does_not_reach_upstream(sample_config) -> None:
    calls = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True})

    transport = _transport(sample_config, upstream)
    sample_config.http.rest_actions["delete_customer"] = RESTActionConfig(
        server_name="customer_database",
        url="https://rest.example/customers/delete",
    )
    try:
        response = await _send_rest_action(transport, "delete_customer", {"customer_id": "C001"})
        assert response.status_code == 403
        assert response.json()["reason"] == "TOOL_DENIED"
        assert calls == 0
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_rest_approval_requires_admin_and_replay_protected(sample_config) -> None:
    client_token = "client-token"
    admin_token = "separate-admin-token"
    sample_config.identity.admin_credentials["operator"] = AdminCredential(
        id="operator-1",
        api_key_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
    )
    calls = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"updated": True})

    transport = _transport(sample_config, upstream)
    sample_config.http.rest_actions["update_customer"] = RESTActionConfig(
        server_name="customer_database",
        url="https://rest.example/customers/update",
    )
    app_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        args = {"customer_id": "C001", "status": "active"}
        pending = await app_client.post(
            "/api/v1/actions/update_customer",
            headers={"Authorization": f"Bearer {client_token}"},
            json=args,
        )
        assert pending.status_code == 202
        approval_id = pending.json()["approval_id"]
        assert calls == 0

        approved = await app_client.post(
            f"/admin/approvals/{approval_id}/decision",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"decision": "approve"},
        )
        assert approved.status_code == 200

        forwarded = await app_client.post(
            "/api/v1/actions/update_customer",
            headers={
                "Authorization": f"Bearer {client_token}",
                "Mcp-Guard-Approval-Id": approval_id,
            },
            json=args,
        )
        assert forwarded.status_code == 200
        assert calls == 1

        replayed = await app_client.post(
            "/api/v1/actions/update_customer",
            headers={
                "Authorization": f"Bearer {client_token}",
                "Mcp-Guard-Approval-Id": approval_id,
            },
            json=args,
        )
        assert replayed.status_code == 403
        assert calls == 1
    finally:
        await app_client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_admin_dashboard_is_only_a_shell_and_data_stays_protected(sample_config) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {}})

    transport = _transport(sample_config, upstream)
    app_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        page = await app_client.get("/admin")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert "Content-Security-Policy" in page.headers
        assert 'id="root"' in page.text
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]

        policy = await app_client.get("/admin/policy")
        approvals = await app_client.get("/admin/approvals")
        assert policy.status_code == 401
        assert approvals.status_code == 401
    finally:
        await app_client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_read_only_admin_endpoints_require_admin_and_hide_credentials(sample_config) -> None:
    admin_token = "operator-only-token"
    sample_config.identity.admin_credentials["operator"] = AdminCredential(
        id="operator-1",
        api_key_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
    )
    sample_config.http = HTTPTransportConfig(
        upstream_url="https://user:password@upstream.example/mcp?api_key=private"
    )
    sample_config.upstreams["private_server"] = UpstreamConfig(
        name="private_server",
        url="https://user:password@upstream.example/mcp?api_key=private",
        env={"TOKEN": "private-env-value"},
    )
    transport = _transport(sample_config, lambda _request: httpx.Response(200, json={}))
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()), base_url="http://gateway.test"
    )
    try:
        paths = (
            "/admin/session",
            "/admin/agents",
            "/admin/servers",
            "/admin/dlp",
            "/admin/audit",
            "/admin/settings",
        )
        for path in paths:
            assert (await client.get(path)).status_code == 401

        headers = {"Authorization": f"Bearer {admin_token}"}
        session = await client.get("/admin/session", headers=headers)
        agents = await client.get("/admin/agents", headers=headers)
        servers = await client.get("/admin/servers", headers=headers)
        dlp = await client.get("/admin/dlp", headers=headers)
        settings = await client.get("/admin/settings", headers=headers)

        assert session.json() == {"administrator_id": "operator-1", "roles": ["admin"]}
        assert "api_key_hash" not in agents.text
        support_agent = next(
            item for item in agents.json()["agents"] if item["id"] == "support-agent-01"
        )
        assert support_agent["authentication_configured"] is True
        assert "user:password" not in servers.text
        assert "api_key=private" not in servers.text
        assert "private-env-value" not in servers.text
        assert dlp.json()["runtime_editing_supported"] is False
        assert "password" not in settings.text
        assert "private-env-value" not in settings.text
    finally:
        await client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_admin_audit_endpoint_filters_and_omits_payload_fields(sample_config) -> None:
    admin_token = "audit-operator-token"
    sample_config.identity.admin_credentials["operator"] = AdminCredential(
        id="operator-1",
        api_key_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
    )
    transport = _transport(sample_config, lambda _request: httpx.Response(200, json={}))
    with open(sample_config.logging.file, "a", encoding="utf-8") as audit_file:
        audit_file.write(
            json.dumps(
                {
                    "timestamp": "2026-11-23T10:00:00+00:00",
                    "agent_id": "support-agent-01",
                    "tenant_id": "bank-a",
                    "server": "customer_database",
                    "method": "tools/call",
                    "tool": "get_customer",
                    "decision": "DENY",
                    "reason_code": "DLP_BLOCKED",
                    "request_id": "req-17",
                    "arguments": {"password": "do-not-return"},
                    "response": "also-do-not-return",
                    "error": "private upstream detail",
                }
            )
            + "\n"
        )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()), base_url="http://gateway.test"
    )
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        filtered = await client.get(
            "/admin/audit?decision=deny&q=DLP_BLOCKED&limit=10", headers=headers
        )
        assert filtered.status_code == 200
        payload = filtered.json()
        assert payload["total"] == 1
        assert payload["events"][0]["tool"] == "get_customer"
        assert "arguments" not in filtered.text
        assert "do-not-return" not in filtered.text
        assert "private upstream detail" not in filtered.text

        invalid = await client.get("/admin/audit?limit=201", headers=headers)
        assert invalid.status_code == 400
    finally:
        await client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_readiness_fails_when_upstream_is_known_unavailable(sample_config) -> None:
    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {}})

    transport = _transport(sample_config, upstream)
    transport._upstream_reachable = False
    app_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        response = await app_client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["upstream_status"] == "unavailable"
    finally:
        await app_client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_unsupported_protocol_returns_supported_versions(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unsupported versions must be rejected before upstream")

    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request("ping", 6)
        message["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2031-01-01"
        response = await _send(transport, message, "ping")
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == -32022
        assert error["data"]["requested"] == "2031-01-01"
        assert CURRENT_PROTOCOL_VERSION in error["data"]["supported"]
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_modern_header_without_body_version_is_header_mismatch(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid modern metadata must be rejected before upstream")

    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request("ping", 7)
        del message["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"]
        response = await _send(transport, message, "ping")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32020
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_denied_tool_call_never_reaches_upstream(sample_config) -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 3, "result": {}})

    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request(
            "tools/call", 3, {"name": "delete_customer", "arguments": {"customer_id": "C1"}}
        )
        response = await _send(transport, message, "tools/call")
        assert response.status_code == 200
        assert response.json()["id"] == 3
        assert response.json()["error"]["code"] == -32001
        assert calls == 0
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_dlp_blocked_tool_arguments_never_reach_upstream(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("DLP-blocked request must not reach upstream")

    sample_config.security.dlp_patterns = [
        DLPPattern(name="ssn", pattern=r"\b\d{3}-\d{2}-\d{4}\b", mode=DLPMode.BLOCK)
    ]
    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request(
            "tools/call",
            8,
            {"name": "get_customer", "arguments": {"customer_id": "123-45-6789"}},
        )
        response = await _send(transport, message, "tools/call")
        assert response.status_code == 200
        assert response.json()["id"] == 8
        assert "data-protection" in response.json()["error"]["message"]
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_sse_response_is_inspected_and_event_fields_are_preserved(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        response = {
            "jsonrpc": "2.0",
            "id": 4,
            "result": {"content": [{"type": "text", "text": "Contact alice@example.com"}]},
        }
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "MCP-Protocol-Version": CURRENT_PROTOCOL_VERSION,
            },
            content=f"id: 4\nevent: message\ndata: {json.dumps(response)}\n\n",
        )

    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request(
            "tools/call", 4, {"name": "get_customer", "arguments": {"customer_id": "C001"}}
        )
        response = await _send(transport, message, "tools/call")
        assert response.status_code == 200
        assert "id: 4" in response.text
        assert "event: message" in response.text
        assert "[REDACTED_EMAIL]" in response.text
        assert "alice@example.com" not in response.text
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_dlp_blocked_upstream_response_is_replaced(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": request_body["id"],
                "result": {"content": [{"type": "text", "text": "SSN 123-45-6789"}]},
            },
        )

    sample_config.security.dlp_patterns = [
        DLPPattern(name="ssn", pattern=r"\b\d{3}-\d{2}-\d{4}\b", mode=DLPMode.BLOCK)
    ]
    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request(
            "tools/call", 9, {"name": "get_customer", "arguments": {"customer_id": "C001"}}
        )
        response = await _send(transport, message, "tools/call")
        assert response.status_code == 200
        assert response.json()["id"] == 9
        assert "error" in response.json()
        assert "123-45-6789" not in response.text
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_encoded_unicode_tool_name_is_validated_and_forwarded(sample_config) -> None:
    received: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 5, "result": {"ok": True}})

    sample_config.policy.agents["support-agent-01"].servers["customer_database"].tools[
        "get_客户"
    ] = ToolPolicy(action=PolicyAction.ALLOW)
    transport = _transport(sample_config, upstream)
    try:
        message = _modern_request(
            "tools/call", 5, {"name": "get_客户", "arguments": {"customer_id": "C001"}}
        )
        response = await _send(transport, message, "tools/call")
        assert response.status_code == 200
        assert response.json()["result"]["ok"] is True
        assert received[0].headers["mcp-name"] == "=?base64?Z2V0X+WuouaItw==?="
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_legacy_notification_202_without_content_type_is_relayed(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    transport = _transport(sample_config, upstream)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer client-token",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert response.status_code == 202
        assert response.content == b""
    finally:
        await client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_oversized_http_request_is_rejected_before_upstream(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("oversized requests must not reach upstream")

    transport = _transport(sample_config, upstream)
    transport.max_message_size = 128
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=transport.create_app()),
        base_url="http://gateway.test",
    )
    try:
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer client-token",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "data": "x" * 512}),
        )
        assert response.status_code == 413
    finally:
        await client.aclose()
        await transport.stop()


@pytest.mark.asyncio
async def test_concurrent_http_requests_keep_response_ids_correlated(sample_config) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": request_body["id"], "result": {"ok": True}},
        )

    transport = _transport(sample_config, upstream)
    try:
        responses = await asyncio.gather(
            *(
                _send(transport, _modern_request("ping", request_id), "ping")
                for request_id in range(10, 18)
            )
        )
        assert [response.json()["id"] for response in responses] == list(range(10, 18))
    finally:
        await transport.stop()
