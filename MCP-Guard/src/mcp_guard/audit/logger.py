"""Security Audit Logger — structured JSONL audit logging."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp_guard.audit.rotation import rotate_log_file
from mcp_guard.core.models import AuditEvent, GatewayConfig, SecurityDecision, ToolCallInfo

logger = logging.getLogger("mcp_guard.audit")

# Characters to sanitize from log values to prevent log injection
LOG_INJECTION_PATTERN = re.compile(r"[\n\r\x00-\x1f]")


def _sanitize_log_value(value: Any) -> Any:
    """Sanitize nested values before JSON serialization."""
    if isinstance(value, str):
        return LOG_INJECTION_PATTERN.sub("", value)
    if isinstance(value, list):
        return [_sanitize_log_value(item) for item in value]
    if isinstance(value, dict):
        return {_sanitize_log_value(key): _sanitize_log_value(item) for key, item in value.items()}
    return value


class AuditLogger:
    """Structured JSON Lines audit logger.

    Writes security decisions to a JSONL file for audit purposes.
    Never logs secrets, tokens, passwords, or full arguments by default.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self._log_file: Optional[Any] = None
        self._log_path = config.logging.file
        self._log_arguments = config.logging.log_arguments
        self._log_responses = config.logging.log_responses
        self._max_size_bytes = config.logging.max_size_mb * 1024 * 1024
        self._backup_count = config.logging.backup_count

        # Ensure log directory exists
        log_dir = Path(self._log_path).parent
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create log directory %s: %s", log_dir, e)

        # Open log file in append mode
        try:
            self._log_file = open(self._log_path, "a", encoding="utf-8")
        except OSError as e:
            logger.error("Failed to open audit log file %s: %s", self._log_path, e)

    def log_decision(
        self,
        decision: SecurityDecision,
        tool_call: Optional[ToolCallInfo] = None,
        method: str = "",
        request_id: Any = None,
        error: Optional[str] = None,
        dlp_findings: Optional[list[str]] = None,
    ) -> None:
        """Log a security decision.

        Args:
            decision: The security decision made.
            tool_call: Optional tool call info.
            method: The MCP method.
            request_id: The JSON-RPC request ID.
            error: Optional error info.
            dlp_findings: Optional DLP pattern matches.
        """
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 -- Python 3.9 source test compatibility
            agent_id=_sanitize_log_value(decision.agent_id),
            tenant_id=_sanitize_log_value(decision.tenant_id) or None,
            user_id=_sanitize_log_value(decision.user_id) or None,
            server=_sanitize_log_value(decision.server_name),
            method=_sanitize_log_value(method or "tools/call"),
            tool=_sanitize_log_value(decision.tool_name),
            correlation_id=_sanitize_log_value(str(request_id)) if request_id is not None else None,
            decision=_sanitize_log_value(decision.decision),
            reason_code=_sanitize_log_value(decision.reason_code),
            request_id=_sanitize_log_value(request_id),
            latency_ms=round(decision.latency_ms, 2),
            error=_sanitize_log_value(error) if error else None,
            dlp_findings=_sanitize_log_value(dlp_findings) if dlp_findings else None,
            arguments=(
                _sanitize_log_value(tool_call.arguments)
                if self._log_arguments and tool_call
                else None
            ),
        )

        self._write_event(event)

    def log_access(
        self,
        agent_id: str,
        server: str,
        method: str,
        decision: str,
        reason_code: str = "",
        request_id: Any = None,
        tool: str = "",
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        arguments: Optional[dict[str, Any]] = None,
        response: Any = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        resource: Optional[str] = None,
        prompt: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Log a simple access event."""
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 -- Python 3.9 source test compatibility
            agent_id=_sanitize_log_value(agent_id),
            tenant_id=_sanitize_log_value(tenant_id) if tenant_id else None,
            user_id=_sanitize_log_value(user_id) if user_id else None,
            server=_sanitize_log_value(server),
            method=_sanitize_log_value(method),
            tool=_sanitize_log_value(tool),
            resource=_sanitize_log_value(resource) if resource else None,
            prompt=_sanitize_log_value(prompt) if prompt else None,
            correlation_id=_sanitize_log_value(correlation_id) if correlation_id else None,
            decision=_sanitize_log_value(decision),
            reason_code=_sanitize_log_value(reason_code),
            request_id=_sanitize_log_value(request_id),
            latency_ms=round(latency_ms, 2),
            error=_sanitize_log_value(error) if error else None,
            arguments=_sanitize_log_value(arguments)
            if self._log_arguments and arguments is not None
            else None,
            response=_sanitize_log_value(response)
            if self._log_responses and response is not None
            else None,
        )
        self._write_event(event)

    def _write_event(self, event: AuditEvent) -> None:
        """Write an audit event to the log file."""
        if self._log_file is None:
            return

        try:
            self._rotate_if_needed()
            if self._log_file is None:
                return
            line = event.model_dump_json(exclude_none=True)
            self._log_file.write(line + "\n")
            self._log_file.flush()
        except Exception as e:
            # Logging must never crash the application
            logger.error("Failed to write audit event: %s", e)

    def _rotate_if_needed(self) -> None:
        """Rotate a full file and reopen the active JSONL stream."""
        try:
            if not Path(self._log_path).exists():
                return
            if Path(self._log_path).stat().st_size < self._max_size_bytes:
                return
            if self._log_file is not None:
                self._log_file.close()
            self._log_file = None
            rotate_log_file(
                self._log_path,
                max_size_mb=self.config.logging.max_size_mb,
                backup_count=self._backup_count,
            )
            self._log_file = open(self._log_path, "a", encoding="utf-8")
        except OSError as e:
            logger.error("Failed to rotate audit log %s: %s", self._log_path, e)
            if self._log_file is None:
                try:
                    self._log_file = open(self._log_path, "a", encoding="utf-8")
                except OSError:
                    logger.error("Failed to reopen audit log %s", self._log_path)

    def close(self) -> None:
        """Close the audit log file."""
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def __del__(self) -> None:
        self.close()
