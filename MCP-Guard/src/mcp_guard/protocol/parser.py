"""MCP JSON-RPC message parser."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp_guard.core.exceptions import ProtocolError
from mcp_guard.core.models import JSONRPCMessage


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    """Reject Python's non-standard NaN and Infinity JSON extensions."""
    raise ValueError(f"Invalid JSON numeric constant: {value}")


def parse_message(raw: str | bytes) -> JSONRPCMessage:
    """Parse a raw JSON string into a JSONRPCMessage.

    Args:
        raw: Raw JSON string or bytes.

    Returns:
        Parsed JSONRPCMessage.

    Raises:
        ProtocolError: If the message is not valid JSON or not a valid JSON-RPC message.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProtocolError("Message is not valid UTF-8") from e

    raw = raw.strip()
    if not raw:
        raise ProtocolError("Empty message received")

    try:
        data = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_constant,
        )
    except (json.JSONDecodeError, ValueError) as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ProtocolError(f"JSON-RPC message must be an object, got {type(data).__name__}")

    return _dict_to_message(data)


def parse_message_permissive(raw: str | bytes) -> Optional[JSONRPCMessage]:
    """Try to parse; return None on failure instead of raising."""
    try:
        return parse_message(raw)
    except Exception:
        return None


def _dict_to_message(data: dict[str, Any]) -> JSONRPCMessage:
    """Validate and convert a dictionary to a JSONRPCMessage."""
    if data.get("jsonrpc") != "2.0":
        raise ProtocolError("Invalid or missing JSON-RPC version")

    has_method = "method" in data
    has_id = "id" in data
    has_result = "result" in data
    has_error = "error" in data

    if has_id:
        request_id = data["id"]
        if request_id is None:
            if has_method or not has_error:
                raise ProtocolError("Null JSON-RPC IDs are only valid on error responses")
        elif isinstance(request_id, bool) or not isinstance(request_id, (str, int, float)):
            raise ProtocolError("Invalid JSON-RPC request ID")

    if has_method:
        method = data["method"]
        if not isinstance(method, str) or not method:
            raise ProtocolError("JSON-RPC method must be a non-empty string")
        if has_result or has_error:
            raise ProtocolError("A JSON-RPC request must not contain result or error")
        if "params" in data and not isinstance(data["params"], dict):
            raise ProtocolError("MCP request params must be an object")
    else:
        if not has_id or has_result == has_error:
            raise ProtocolError("Invalid JSON-RPC response structure")
        if has_error:
            error = data["error"]
            if (
                not isinstance(error, dict)
                or isinstance(error.get("code"), bool)
                or not isinstance(error.get("code"), int)
                or not isinstance(error.get("message"), str)
            ):
                raise ProtocolError("Invalid JSON-RPC error object")

    fields = {
        key: data[key]
        for key in ("jsonrpc", "id", "method", "params", "result", "error")
        if key in data
    }
    try:
        return JSONRPCMessage(**fields)
    except Exception as e:
        raise ProtocolError("Invalid JSON-RPC message fields") from e


def parse_batch(raw: str | bytes) -> list[JSONRPCMessage]:
    """Parse a potential batch JSON-RPC message.

    Returns a list of messages (single-element for non-batch).

    Raises:
        ProtocolError: On invalid JSON.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProtocolError("Message is not valid UTF-8") from e

    raw = raw.strip()
    if not raw:
        raise ProtocolError("Empty message received")

    try:
        data = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_constant,
        )
    except (json.JSONDecodeError, ValueError) as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    if isinstance(data, list):
        if not data:
            raise ProtocolError("Empty JSON-RPC batch")
        if any(not isinstance(item, dict) for item in data):
            raise ProtocolError("JSON-RPC batch members must be objects")
        return [_dict_to_message(item) for item in data]
    elif isinstance(data, dict):
        return [_dict_to_message(data)]
    else:
        raise ProtocolError(f"Unexpected JSON type: {type(data).__name__}")


def serialize_message(msg: JSONRPCMessage) -> str:
    """Serialize a JSONRPCMessage back to JSON string."""
    data: dict[str, Any] = {"jsonrpc": msg.jsonrpc}

    if msg.has_id:
        data["id"] = msg.id

    if msg.method is not None:
        data["method"] = msg.method

    if msg.params is not None:
        data["params"] = msg.params

    if msg.has_result:
        data["result"] = msg.result

    if msg.has_error:
        data["error"] = msg.error

    return json.dumps(data, separators=(",", ":"))


def create_error_response(
    request_id: Any,
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> str:
    """Create a JSON-RPC error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data

    response = JSONRPCMessage(
        jsonrpc="2.0",
        id=request_id,
        error=error,
    )
    return serialize_message(response)


def create_result_response(request_id: Any, result: Any) -> str:
    """Create a JSON-RPC success response."""
    response = JSONRPCMessage(
        jsonrpc="2.0",
        id=request_id,
        result=result,
    )
    return serialize_message(response)
