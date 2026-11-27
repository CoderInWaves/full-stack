"""Contract tests for the lightweight MCP-Guard Python SDK."""

from __future__ import annotations

import json

import httpx
import pytest

from mcp_guard.sdk import MCPGuard, MCPGuardApprovalRequired, MCPGuardAuthorizationError


def test_sdk_sends_modern_mcp_headers_and_returns_tools() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/mcp"
        assert request.headers["authorization"] == "Bearer sdk-token"
        assert request.headers["mcp-method"] == "tools/list"
        assert request.headers["mcp-protocol-version"] == "2026-07-28"
        assert payload["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"] == {}
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [{"name": "read"}]}},
        )

    client = httpx.Client(transport=httpx.MockTransport(upstream))
    guard = MCPGuard("https://guard.example", "sdk-token", client=client)
    assert guard.list_tools() == {"tools": [{"name": "read"}]}
    client.close()


def test_sdk_maps_policy_denial_to_structured_exception() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.headers["mcp-method"] == "tools/call"
        assert request.headers["mcp-name"] == "delete_customer"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "error": {
                    "code": -32001,
                    "message": "Access denied",
                    "data": {"reason": "TOOL_DENIED"},
                },
            },
        )

    guard = MCPGuard(
        "https://guard.example",
        "sdk-token",
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
    )
    with pytest.raises(MCPGuardAuthorizationError) as captured:
        guard.call_tool("delete_customer", {"customer_id": "C001"})
    assert captured.value.data == {"reason": "TOOL_DENIED"}


def test_sdk_surfaces_approval_id_without_logging_arguments() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "error": {
                    "code": -32001,
                    "message": "Approval required",
                    "data": {"reason": "APPROVAL_REQUIRED", "approval_id": "approval-1"},
                },
            },
        )

    guard = MCPGuard(
        "https://guard.example",
        "sdk-token",
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
    )
    with pytest.raises(MCPGuardApprovalRequired) as captured:
        guard.call_tool("update_customer", {"email": "sensitive@example.com"})
    assert captured.value.approval_id == "approval-1"
    assert "sensitive@example.com" not in str(captured.value)


def test_sdk_can_retry_exact_tool_with_approval_metadata() -> None:
    observed: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append(payload)
        if len(observed) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {
                        "code": -32001,
                        "message": "Approval required",
                        "data": {"reason": "APPROVAL_REQUIRED", "approval_id": "approved-7"},
                    },
                },
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"updated": True}},
        )

    guard = MCPGuard(
        "https://guard.example",
        "sdk-token",
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
    )
    arguments = {"customer_id": "C001", "status": "active"}
    with pytest.raises(MCPGuardApprovalRequired) as captured:
        guard.call_tool("update_customer", arguments)
    assert captured.value.approval_id == "approved-7"
    assert guard.call_tool("update_customer", arguments, approval_id="approved-7") == {
        "updated": True
    }
    assert observed[1]["params"]["arguments"] == arguments
    assert observed[1]["params"]["_meta"]["io.mcp-guard/approvalId"] == "approved-7"


def test_protect_returns_remote_action_wrappers_not_local_execution() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    guard = MCPGuard(
        "https://guard.example/root",
        "sdk-token",
        client=httpx.Client(transport=httpx.MockTransport(upstream)),
    )
    wrappers = guard.protect(["get_customer"])
    assert wrappers["get_customer"](customer_id="C001") == {"ok": True}
    assert calls == [("/root/api/v1/actions/get_customer", {"customer_id": "C001"})]
