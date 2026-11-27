"""Unit tests for the protocol parser."""

from __future__ import annotations

import json

import pytest

from mcp_guard.core.exceptions import ProtocolError
from mcp_guard.protocol.parser import (
    create_error_response,
    create_result_response,
    parse_batch,
    parse_message,
    parse_message_permissive,
    serialize_message,
)


class TestParseMessage:
    def test_valid_request(self) -> None:
        raw = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "test"}}
        )
        msg = parse_message(raw)
        assert msg.jsonrpc == "2.0"
        assert msg.id == 1
        assert msg.method == "tools/call"
        assert msg.params == {"name": "test"}
        assert msg.is_request

    def test_valid_notification(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        msg = parse_message(raw)
        assert msg.is_notification
        assert not msg.is_request

    def test_valid_response(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})
        msg = parse_message(raw)
        assert msg.is_response
        assert not msg.is_request

    def test_error_response(self) -> None:
        raw = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Not found"}}
        )
        msg = parse_message(raw)
        assert msg.is_error
        assert msg.is_response

    def test_invalid_json(self) -> None:
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            parse_message("{not valid json")

    def test_empty_message(self) -> None:
        with pytest.raises(ProtocolError, match="Empty message"):
            parse_message("")

    def test_duplicate_keys_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="Duplicate JSON object key"):
            parse_message('{"jsonrpc":"2.0","jsonrpc":"2.0","id":1,"method":"ping"}')

    def test_null_result_is_preserved(self) -> None:
        message = parse_message('{"jsonrpc":"2.0","id":0,"result":null}')
        assert message.has_id
        assert message.id == 0
        assert message.has_result
        assert serialize_message(message) == '{"jsonrpc":"2.0","id":0,"result":null}'

    def test_null_id_on_success_response_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="Null JSON-RPC IDs"):
            parse_message('{"jsonrpc":"2.0","id":null,"result":{}}')

    def test_non_object_json(self) -> None:
        with pytest.raises(ProtocolError, match="must be an object"):
            parse_message("[1, 2, 3]")

    def test_bytes_input(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        msg = parse_message(raw)
        assert msg.method == "ping"

    def test_permissive_returns_none_on_error(self) -> None:
        assert parse_message_permissive("bad json") is None
        assert parse_message_permissive("") is None

    def test_permissive_returns_message(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msg = parse_message_permissive(raw)
        assert msg is not None
        assert msg.method == "ping"


class TestParseBatch:
    def test_single_message(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msgs = parse_batch(raw)
        assert len(msgs) == 1

    def test_batch_messages(self) -> None:
        raw = json.dumps(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
        )
        msgs = parse_batch(raw)
        assert len(msgs) == 2
        assert msgs[0].method == "ping"
        assert msgs[1].method == "tools/list"

    def test_empty_batch(self) -> None:
        with pytest.raises(ProtocolError, match="Empty"):
            parse_batch("[]")


class TestSerialize:
    def test_serialize_roundtrip(self) -> None:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        msg = parse_message(raw)
        serialized = serialize_message(msg)
        reparsed = json.loads(serialized)
        assert reparsed["jsonrpc"] == "2.0"
        assert reparsed["id"] == 1
        assert reparsed["method"] == "ping"

    def test_create_error_response(self) -> None:
        resp = create_error_response(42, -32001, "Access denied")
        data = json.loads(resp)
        assert data["id"] == 42
        assert data["error"]["code"] == -32001
        assert "Access denied" in data["error"]["message"]

    def test_create_result_response(self) -> None:
        resp = create_result_response(7, {"status": "ok"})
        data = json.loads(resp)
        assert data["id"] == 7
        assert data["result"]["status"] == "ok"

    def test_error_response_preserves_id(self) -> None:
        """Verify error responses preserve the request ID."""
        resp = create_error_response(99, -32001, "Denied")
        data = json.loads(resp)
        assert data["id"] == 99
