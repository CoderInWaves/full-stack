"""Process management utilities for STDIO transport."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Optional

logger = logging.getLogger("mcp_guard.process")


async def start_upstream_process(
    command: Sequence[str],
    env: Optional[dict[str, str]] = None,
    max_buffer_size: int = 1048577,
) -> asyncio.subprocess.Process:
    """Start an upstream MCP server as a subprocess.

    Args:
        command: Command and arguments to run. Must not use shell=True.
        env: Optional environment variables to pass.

    Returns:
        The subprocess.

    Raises:
        OSError: If the process cannot be started.
    """
    # Build environment
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    # Validate command is not empty
    if not command:
        raise ValueError("Upstream command must not be empty")
    if any(not isinstance(part, str) or not part or "\x00" in part for part in command):
        raise ValueError("Upstream command arguments must be non-empty strings without null bytes")

    # Never use shell=True
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=process_env,
        limit=max_buffer_size,
    )

    logger.info("Started upstream process PID=%d command=%s", proc.pid, command[0])
    return proc


async def terminate_process(proc: asyncio.subprocess.Process, timeout: float = 5.0) -> None:
    """Gracefully terminate a subprocess.

    Sends SIGTERM first, then SIGKILL after timeout.
    """
    if proc.returncode is not None:
        return  # Already exited

    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("Process PID=%d did not exit after SIGTERM, sending SIGKILL", proc.pid)
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass  # Already gone
    except Exception as e:
        logger.error("Error terminating process: %s", e)


async def drain_stderr(proc: asyncio.subprocess.Process) -> None:
    """Drain upstream stderr without copying its potentially sensitive text."""
    if proc.stderr is None:
        return

    try:
        while True:
            chunk = await proc.stderr.read(8192)
            if not chunk:
                break
            logger.debug("Drained %d bytes from upstream stderr", len(chunk))
    except Exception:
        pass
