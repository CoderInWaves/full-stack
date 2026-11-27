"""STDIO proxy transport for one MCP client and one configured upstream."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any, Optional

from mcp_guard.audit.logger import AuditLogger
from mcp_guard.core.constants import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_REDACT,
    METHOD_TOOLS_CALL,
)
from mcp_guard.core.models import GatewayConfig, JSONRPCMessage
from mcp_guard.protocol.message_router import MessageRouter
from mcp_guard.protocol.parser import (
    create_error_response,
    parse_message_permissive,
)
from mcp_guard.security.tool_controller import ToolAccessController
from mcp_guard.transports.base import BaseTransport
from mcp_guard.utils.process import drain_stderr, start_upstream_process, terminate_process

logger = logging.getLogger("mcp_guard.stdio")


class STDIOTransport(BaseTransport):
    """Inspect newline-framed messages between stdin/stdout and an upstream."""

    def __init__(
        self,
        config: GatewayConfig,
        upstream_command: list[str],
        upstream_env: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(config)
        self.upstream_command = upstream_command
        self.upstream_env = upstream_env or {}
        self._upstream_proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._pending_methods: dict[Any, str] = {}
        self._pending_started: dict[Any, float] = {}

        self.tool_controller = ToolAccessController(config)
        self.message_router = MessageRouter(config, self.tool_controller)
        self.audit_logger = AuditLogger(config)
        self.agent_id = config.identity.agent_id
        self.identity_context = self.tool_controller.context_for_agent(self.agent_id)
        self.server_name = (
            config.stdio.upstream.name if config.stdio and config.stdio.upstream else ""
        )

    async def start(self) -> None:
        """Launch the upstream and run both protocol directions."""
        logger.info("Starting STDIO proxy for upstream command: %s", self.upstream_command[0])
        try:
            self._upstream_proc = await start_upstream_process(
                self.upstream_command,
                env=self.upstream_env,
                max_buffer_size=self.config.security.max_message_size + 1,
            )
            self._running = True
            self._stderr_task = asyncio.create_task(drain_stderr(self._upstream_proc))

            stdin_task = asyncio.create_task(self._read_stdin_forward_upstream())
            upstream_task = asyncio.create_task(self._read_upstream_forward_stdout())
            done, pending = await asyncio.wait(
                {stdin_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if upstream_task in done and self._pending_methods:
                await self._fail_pending("Upstream process exited")

            if stdin_task in done:
                await stdin_task
                await self._close_upstream_stdin()
                try:
                    await asyncio.wait_for(upstream_task, timeout=5.0)
                except TimeoutError:
                    logger.warning("Upstream did not stop after client stdin closed")
            else:
                self._running = False
                await self._fail_pending("Upstream process exited")

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("STDIO proxy cancelled")
            raise
        except Exception as e:
            logger.error("STDIO proxy error: %s", e)
            raise
        finally:
            self._running = False
            await self.stop()

    async def stop(self) -> None:
        """Terminate the upstream and close the audit file."""
        self._running = False
        await self._close_upstream_stdin()
        if self._upstream_proc:
            await terminate_process(self._upstream_proc)
            self._upstream_proc = None
        if self._stderr_task:
            if not self._stderr_task.done():
                self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None
        self.audit_logger.close()

    async def _read_stdin_forward_upstream(self) -> None:
        """Read bounded client frames, enforce policy, and write upstream."""
        reader = asyncio.StreamReader(limit=self.config.security.max_message_size + 1)
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        while self._running and self._upstream_proc and self._upstream_proc.returncode is None:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            except TimeoutError:
                continue
            except (ValueError, asyncio.LimitOverrunError):
                self._write_stdout(
                    create_error_response(None, -32600, "Message exceeds the configured limit")
                )
                self._running = False
                break
            except Exception as e:
                logger.warning("Failed to read client STDIO: %s", e)
                break

            if not line:
                break
            frame = line.rstrip(b"\r\n")
            if len(frame) > self.config.security.max_message_size:
                self._write_stdout(
                    create_error_response(None, -32600, "Message exceeds the configured limit")
                )
                self._running = False
                break

            try:
                raw = frame.decode("utf-8")
            except UnicodeDecodeError:
                self._write_stdout(
                    create_error_response(None, -32700, "Message is not valid UTF-8")
                )
                continue
            if not raw.strip():
                continue

            parsed = parse_message_permissive(raw)
            forward_message, error_response = self.message_router.process_request(
                raw, self.agent_id, self.server_name, self.identity_context
            )
            if error_response:
                self._write_stdout(error_response)
                reason = "DLP_BLOCKED" if "data-protection" in error_response else "POLICY_DENIED"
                self._audit_request(parsed, DECISION_DENY, reason, raw)
                continue
            if forward_message is None:
                continue

            if parsed and parsed.is_request:
                if parsed.id in self._pending_methods:
                    self._write_stdout(
                        create_error_response(parsed.id, -32600, "Request ID is already in use")
                    )
                    continue

            if not await self._write_upstream(forward_message):
                if parsed and parsed.is_request:
                    self._write_stdout(
                        create_error_response(parsed.id, -32603, "Upstream process is unavailable")
                    )
                self._running = False
                break

            if parsed and parsed.is_request:
                self._pending_methods[parsed.id] = parsed.method or ""
                self._pending_started[parsed.id] = time.monotonic()
            if parsed and parsed.is_request:
                self._audit_request(parsed, DECISION_ALLOW, "", forward_message)

    async def _read_upstream_forward_stdout(self) -> None:
        """Read upstream frames, enforce response limits, and write valid JSON-RPC."""
        if not self._upstream_proc or not self._upstream_proc.stdout:
            return

        while self._running and self._upstream_proc.returncode is None:
            try:
                line = await asyncio.wait_for(self._upstream_proc.stdout.readline(), timeout=1.0)
            except TimeoutError:
                if self._has_timed_out_request():
                    await self._fail_pending("Upstream request timed out")
                    self._running = False
                    return
                continue
            except (ValueError, asyncio.LimitOverrunError):
                logger.error("Upstream emitted an oversized STDIO frame")
                await self._fail_pending("Upstream response exceeded the configured limit")
                self._running = False
                return
            except Exception as e:
                logger.warning("Failed to read upstream STDIO: %s", e)
                break

            if not line:
                logger.info("Upstream process closed stdout")
                await self._fail_pending("Upstream process exited")
                self._running = False
                return
            if len(line) > self.config.security.max_message_size:
                await self._fail_pending("Upstream response exceeded the configured limit")
                self._running = False
                return

            try:
                raw = line.decode("utf-8").rstrip("\n\r")
            except UnicodeDecodeError:
                logger.warning("Dropped non-UTF-8 upstream frame")
                continue
            if not raw.strip():
                continue

            parsed = parse_message_permissive(raw)
            if parsed is None:
                logger.warning("Dropped malformed upstream JSON-RPC frame")
                continue
            pending_method = None
            if parsed.is_response and parsed.id is not None:
                pending_method = self._pending_methods.pop(parsed.id, None)
                self._pending_started.pop(parsed.id, None)
            processed, reason_code = self.message_router.process_response_with_decision(
                raw,
                self.agent_id,
                self.server_name,
                pending_method,
                self.identity_context,
                parsed.id if parsed.is_response else None,
            )
            if parse_message_permissive(processed) is None:
                logger.error("Dropped invalid processed upstream frame")
                continue
            self._write_stdout(processed)
            if reason_code:
                self.audit_logger.log_access(
                    agent_id=self.agent_id,
                    server=self.server_name,
                    method=pending_method or "",
                    decision=(DECISION_DENY if reason_code == "DLP_BLOCKED" else DECISION_REDACT),
                    reason_code=reason_code,
                    request_id=parsed.id if parsed.has_id else None,
                    response=self._json_for_optional_audit(processed),
                )

    async def _write_upstream(self, message: str) -> bool:
        """Write one complete line and apply subprocess pipe backpressure."""
        if not self._upstream_proc or not self._upstream_proc.stdin:
            logger.error("Upstream process is not available")
            return False
        try:
            self._upstream_proc.stdin.write((message + "\n").encode("utf-8"))
            await asyncio.wait_for(
                self._upstream_proc.stdin.drain(),
                timeout=self.config.security.request_timeout_seconds,
            )
            return True
        except (TimeoutError, BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error("Failed to write to upstream process: %s", e)
            return False

    def _write_stdout(self, message: str) -> None:
        """Write only validated JSON-RPC messages to the MCP client."""
        try:
            if parse_message_permissive(message) is None:
                logger.error("Refusing to write invalid JSON-RPC to stdout")
                return
            sys.stdout.buffer.write((message + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()
        except Exception as e:
            logger.error("Failed to write to stdout: %s", e)

    async def _close_upstream_stdin(self) -> None:
        """Signal graceful upstream shutdown by closing its input stream."""
        if self._upstream_proc and self._upstream_proc.stdin:
            try:
                if not self._upstream_proc.stdin.is_closing():
                    self._upstream_proc.stdin.close()
                    await self._upstream_proc.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def _has_timed_out_request(self) -> bool:
        now = time.monotonic()
        timeout = self.config.security.request_timeout_seconds
        return any(now - started >= timeout for started in self._pending_started.values())

    async def _fail_pending(self, reason: str) -> None:
        """Fail in-flight requests before shutting down a broken upstream."""
        for request_id in list(self._pending_methods):
            self._write_stdout(create_error_response(request_id, -32603, reason))
        self._pending_methods.clear()
        self._pending_started.clear()

    def _audit_request(
        self,
        parsed: Optional[JSONRPCMessage],
        decision: str,
        reason_code: str,
        message: str,
    ) -> None:
        if not parsed or not parsed.is_request:
            return
        params = parsed.params or {}
        tool = params.get("name", "") if parsed.method == METHOD_TOOLS_CALL else ""
        args: Any = None
        if parsed.method in {METHOD_TOOLS_CALL, "prompts/get"}:
            args = params.get("arguments", {})
            if not isinstance(args, dict):
                args = None
        forwarded = parse_message_permissive(message)
        if (
            decision == DECISION_ALLOW
            and parsed.method == METHOD_TOOLS_CALL
            and forwarded
            and isinstance(forwarded.params, dict)
        ):
            forwarded_args = forwarded.params.get("arguments")
            if isinstance(forwarded_args, dict):
                args = forwarded_args
        self.audit_logger.log_access(
            agent_id=self.agent_id,
            server=self.server_name,
            method=parsed.method or "",
            decision=decision,
            reason_code=reason_code,
            request_id=parsed.id,
            tool=tool if isinstance(tool, str) else "",
            arguments=args,
            tenant_id=self.identity_context.tenant_id if self.identity_context else None,
            user_id=self.identity_context.user_id if self.identity_context else None,
            resource=(
                params.get("uri")
                if parsed.method == "resources/read" and isinstance(params.get("uri"), str)
                else None
            ),
            prompt=(
                params.get("name")
                if parsed.method == "prompts/get" and isinstance(params.get("name"), str)
                else None
            ),
            correlation_id=str(parsed.id),
        )

    @staticmethod
    def _json_for_optional_audit(value: str) -> Any:
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
