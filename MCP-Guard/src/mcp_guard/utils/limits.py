"""Rate limiting and size limiting utilities."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Optional, TypeVar

T = TypeVar("T")


class MessageSizeLimiter:
    """Enforces message size limits."""

    def __init__(self, max_size: int) -> None:
        self.max_size = max_size

    def check(self, data: bytes | str) -> bool:
        """Return True if the message is within size limits."""
        size = len(data) if isinstance(data, bytes) else len(data.encode("utf-8"))
        return size <= self.max_size


class TimeoutManager:
    """Manages operation timeouts."""

    def __init__(self, default_timeout: float) -> None:
        self.default_timeout = default_timeout

    async def with_timeout(self, coro: Awaitable[T], timeout: Optional[float] = None) -> T:
        """Run a coroutine with a timeout."""
        t = timeout or self.default_timeout
        return await asyncio.wait_for(coro, timeout=t)
