"""Single-process, exact-action human approval queue."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp_guard.core.models import IdentityContext, ToolCallInfo

MAX_APPROVAL_RECORDS = 10_000


@dataclass
class _Approval:
    approval_id: str
    fingerprint: str
    agent_id: str
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]
    server_name: str
    tool_name: str
    created_at: str
    expires_at: str
    expires_monotonic: float
    state: str = "pending"
    approver_id: str = ""
    decided_at: str = ""
    consumed: bool = False


class ApprovalService:
    """Create one-time approvals bound to immutable action fingerprints.

    Records and the HMAC key live in process memory. This service is suitable
    for a single gateway process and deliberately fails closed after restart.
    """

    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = ttl_seconds
        self._key = secrets.token_bytes(32)
        self._records: dict[str, _Approval] = {}
        self._lock = threading.RLock()

    def create(self, call: ToolCallInfo) -> dict[str, Any]:
        """Queue an approval for the exact tool action and trusted identity."""
        now = datetime.now(UTC)
        record = _Approval(
            approval_id=secrets.token_urlsafe(24),
            fingerprint=self._fingerprint(call),
            agent_id=call.agent_id,
            tenant_id=call.identity_context.tenant_id if call.identity_context else call.tenant_id,
            user_id=call.identity_context.user_id if call.identity_context else call.user_id,
            roles=tuple(
                sorted(call.identity_context.roles if call.identity_context else call.roles)
            ),
            server_name=call.server_name,
            tool_name=call.tool_name,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            expires_monotonic=time.monotonic() + self.ttl_seconds,
        )
        with self._lock:
            self._expire_pending()
            if len(self._records) >= MAX_APPROVAL_RECORDS and all(
                item.state == "pending" for item in self._records.values()
            ):
                raise OverflowError("Approval queue is full")
            self._records[record.approval_id] = record
            self._trim_records()
        return self._view(record)

    def decide(self, approval_id: str, approver_id: str, approve: bool) -> dict[str, Any]:
        """Approve or reject a still-pending request exactly once."""
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                raise KeyError("Approval request was not found")
            self._expire_record(record)
            if record.state != "pending":
                raise ValueError(f"Approval request is already {record.state}")
            if not approver_id or approver_id == record.agent_id:
                raise ValueError("An independent administrator must decide this request")
            record.state = "approved" if approve else "rejected"
            record.approver_id = approver_id
            record.decided_at = datetime.now(UTC).isoformat()
            return self._view(record)

    def authorize_once(
        self, approval_id: str, call: ToolCallInfo, context: IdentityContext
    ) -> tuple[bool, str]:
        """Consume an approval only when identity and action match exactly."""
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                return False, "APPROVAL_NOT_FOUND"
            self._expire_record(record)
            if record.consumed:
                return False, "APPROVAL_REPLAYED"
            if record.state != "approved":
                return False, "APPROVAL_NOT_GRANTED"
            expected = self._fingerprint(call)
            if not hmac.compare_digest(record.fingerprint, expected):
                return False, "APPROVAL_ACTION_MISMATCH"
            if (
                record.agent_id != context.agent_id
                or record.tenant_id != context.tenant_id
                or record.user_id != context.user_id
                or record.roles != tuple(sorted(context.roles))
            ):
                return False, "APPROVAL_IDENTITY_MISMATCH"
            record.consumed = True
            record.state = "consumed"
            record.decided_at = record.decided_at or datetime.now(UTC).isoformat()
            return True, "APPROVAL_GRANTED"

    def list_requests(self, state: str = "") -> list[dict[str, Any]]:
        """Return redacted request metadata for the administrator queue."""
        with self._lock:
            self._expire_pending()
            records = sorted(self._records.values(), key=lambda item: item.created_at)
            return [self._view(record) for record in records if not state or record.state == state]

    def _fingerprint(self, call: ToolCallInfo) -> str:
        context = call.identity_context or IdentityContext(
            agent_id=call.agent_id,
            tenant_id=call.tenant_id,
            user_id=call.user_id,
            roles=call.roles,
        )
        payload = {
            "method": "tools/call",
            "agent_id": context.agent_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "roles": sorted(context.roles),
            "server_name": call.server_name,
            "tool_name": call.tool_name,
            "arguments": call.arguments,
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return hmac.new(self._key, canonical, hashlib.sha256).hexdigest()

    def _expire_pending(self) -> None:
        for record in self._records.values():
            self._expire_record(record)

    @staticmethod
    def _expire_record(record: _Approval) -> None:
        if record.state == "pending" and time.monotonic() >= record.expires_monotonic:
            record.state = "expired"

    def _trim_records(self) -> None:
        while len(self._records) > MAX_APPROVAL_RECORDS:
            removable = next(
                (key for key, item in self._records.items() if item.state != "pending"), None
            )
            if removable is None:
                raise OverflowError("Approval queue is full")
            else:
                self._records.pop(removable, None)

    @staticmethod
    def _view(record: _Approval) -> dict[str, Any]:
        return {
            "approval_id": record.approval_id,
            "agent_id": record.agent_id,
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "server": record.server_name,
            "tool": record.tool_name,
            "state": record.state,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "approver_id": record.approver_id or None,
            "decided_at": record.decided_at or None,
            "consumed": record.consumed,
        }
