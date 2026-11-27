"""Small synchronous HTTP client for MCP-Guard MCP and REST action endpoints."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Mapping
from typing import Any, Callable
from urllib.parse import quote, urljoin

import httpx

from mcp_guard.sdk.errors import (
    MCPGuardApprovalRequired,
    MCPGuardAuthenticationError,
    MCPGuardAuthorizationError,
    MCPGuardProtocolError,
    MCPGuardTransportError,
)

CURRENT_PROTOCOL_VERSION = "2026-07-28"


class MCPGuard:
    """Call protected tools/actions through one MCP-Guard HTTP gateway.

    The SDK never executes supplied local functions. ``protect`` creates
    wrappers that send requests to the gateway, where identity, policy, and
    DLP checks run again on every operation.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self._ids = itertools.count(1)
        self._session_id: str | None = None

    def close(self) -> None:
        """Close the internally created HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MCPGuard:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def list_tools(self, cursor: str | None = None) -> dict[str, Any]:
        """Return the policy-filtered tools/list result from MCP-Guard."""
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return self.request("tools/list", params)

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Call one MCP tool; access is decided by MCP-Guard's policy engine."""
        return self.request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
            approval_id=approval_id,
        )

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one modern MCP request and return its ``result`` object."""
        request_id = next(self._ids)
        metadata: dict[str, Any] = {
            "io.modelcontextprotocol/protocolVersion": CURRENT_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "mcp-guard-python", "version": "0.1"},
        }
        if approval_id:
            metadata["io.mcp-guard/approvalId"] = approval_id
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": {
                **dict(params or {}),
                "_meta": metadata,
            },
        }
        headers = self._headers(method, body["params"])
        response = self._send("/mcp", body, headers)
        if response.status_code == 401:
            raise MCPGuardAuthenticationError(
                "MCP-Guard rejected the configured credential", status_code=401
            )
        if response.status_code >= 400:
            raise MCPGuardTransportError(
                f"MCP-Guard returned HTTP {response.status_code}", status_code=response.status_code
            )
        message = self._decode_mcp_response(response)
        if not isinstance(message, dict) or message.get("id") != request_id:
            raise MCPGuardProtocolError("MCP-Guard returned a mismatched JSON-RPC response")
        error = message.get("error")
        if isinstance(error, dict):
            data = error.get("data")
            reason = data.get("reason") if isinstance(data, dict) else None
            if reason == "APPROVAL_REQUIRED":
                raise MCPGuardApprovalRequired(
                    str(error.get("message", "Approval required")),
                    approval_id=data.get("approval_id") if isinstance(data, dict) else None,
                    status_code=response.status_code,
                    code=error.get("code"),
                    data=data,
                )
            if error.get("code") == -32001:
                raise MCPGuardAuthorizationError(
                    str(error.get("message", "Access denied")),
                    status_code=response.status_code,
                    code=error.get("code"),
                    data=data,
                )
            raise MCPGuardProtocolError(
                str(error.get("message", "MCP request failed")),
                status_code=response.status_code,
                code=error.get("code"),
                data=data,
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise MCPGuardProtocolError("MCP-Guard response has no result object")
        return result

    def call_action(
        self,
        action: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approval_id: str | None = None,
    ) -> Any:
        """Call a statically configured direct REST action through the gateway."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if approval_id:
            headers["Mcp-Guard-Approval-Id"] = approval_id
        try:
            response = self._client.post(
                urljoin(self.base_url, f"api/v1/actions/{quote(action, safe='')}"),
                headers=headers,
                json=dict(arguments or {}),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise MCPGuardTransportError("Could not reach MCP-Guard") from exc
        if response.status_code == 401:
            raise MCPGuardAuthenticationError(
                "MCP-Guard rejected the configured credential", status_code=401
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text}
        if response.status_code == 202 and isinstance(payload, dict):
            raise MCPGuardApprovalRequired(
                str(payload.get("error", "Approval required")),
                approval_id=payload.get("approval_id"),
                status_code=202,
                data=payload,
            )
        if response.status_code == 403:
            raise MCPGuardAuthorizationError(
                str(payload.get("error", "Access denied"))
                if isinstance(payload, dict)
                else "Access denied",
                status_code=403,
                data=payload,
            )
        if response.status_code >= 400:
            raise MCPGuardTransportError(
                str(payload.get("error", f"HTTP {response.status_code}"))
                if isinstance(payload, dict)
                else f"HTTP {response.status_code}",
                status_code=response.status_code,
                data=payload,
            )
        return payload

    def protect(self, tools: Iterable[Any] | Mapping[str, Any]) -> dict[str, Callable[..., Any]]:
        """Build named callables that route action calls through the REST gateway.

        ``tools`` may be action-name strings, a mapping whose keys are action
        names, or framework tool objects with a ``name`` attribute. Local
        function bodies are intentionally not called.
        """
        if isinstance(tools, Mapping):
            names = list(tools.keys())
        else:
            names = [
                tool if isinstance(tool, str) else getattr(tool, "name", None) for tool in tools
            ]
        wrapped: dict[str, Callable[..., Any]] = {}
        for name in names:
            if not isinstance(name, str) or not name:
                raise ValueError("Each protected tool must have a non-empty action name")

            def action_wrapper(_action: str = name, **arguments: Any) -> Any:
                return self.call_action(_action, arguments)

            action_wrapper.__name__ = name
            action_wrapper.__doc__ = f"Call the MCP-Guard protected action {name}."
            wrapped[name] = action_wrapper
        return wrapped

    def _headers(self, method: str, params: dict[str, Any]) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": CURRENT_PROTOCOL_VERSION,
            "Mcp-Method": method,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if method == "tools/call":
            headers["Mcp-Name"] = self._encode_header_value(params["name"])
        elif method == "resources/read":
            headers["Mcp-Name"] = self._encode_header_value(params["uri"])
        elif method == "prompts/get":
            headers["Mcp-Name"] = self._encode_header_value(params["name"])
        return headers

    @staticmethod
    def _encode_header_value(value: str) -> str:
        """Encode protocol names that cannot be represented safely as headers."""
        import base64

        safe_ascii = all(0x21 <= ord(char) <= 0x7E or char in " \t" for char in value)
        padded = value.startswith((" ", "\t")) or value.endswith((" ", "\t"))
        sentinel = value.startswith("=?base64?") and value.endswith("?=")
        if safe_ascii and not padded and not sentinel:
            return value
        return f"=?base64?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="

    def _send(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        try:
            response = self._client.post(
                urljoin(self.base_url, path.lstrip("/")),
                headers=headers,
                content=json.dumps(
                    body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise MCPGuardTransportError("Could not reach MCP-Guard") from exc
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        return response

    @staticmethod
    def _decode_mcp_response(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "").lower()
        if "json" in content_type:
            try:
                return response.json()
            except ValueError as exc:
                raise MCPGuardProtocolError("MCP-Guard returned invalid JSON") from exc
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    value = line[5:].lstrip()
                    try:
                        return json.loads(value)
                    except ValueError:
                        continue
        raise MCPGuardProtocolError("MCP-Guard returned an unsupported response type")
