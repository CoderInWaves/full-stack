"""Base transport interface."""

from __future__ import annotations

import abc

from mcp_guard.core.models import GatewayConfig


class BaseTransport(abc.ABC):
    """Abstract base for MCP-Guard transports."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the transport."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop the transport and clean up resources."""
