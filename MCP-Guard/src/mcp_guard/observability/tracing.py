"""Optional OpenTelemetry tracing with no effect on authorization decisions."""

from __future__ import annotations

import logging
import os
from contextlib import AbstractContextManager, nullcontext
from typing import Any, cast

logger = logging.getLogger("mcp_guard.tracing")


class TracingManager:
    """Create safe, payload-free spans when optional OpenTelemetry is installed."""

    def __init__(self, service_name: str) -> None:
        self._tracer: Any = None
        self._owned_provider: Any = None
        try:
            from opentelemetry import trace
        except ImportError:
            return

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry import trace as trace_api
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                from opentelemetry.trace import ProxyTracerProvider

                if isinstance(trace_api.get_tracer_provider(), ProxyTracerProvider):
                    provider = TracerProvider(
                        resource=Resource.create({"service.name": service_name})
                    )
                    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                    trace_api.set_tracer_provider(provider)
                    self._owned_provider = provider
            except ImportError:
                logger.warning(
                    "OTEL_EXPORTER_OTLP_ENDPOINT is set, but install MCP-Guard's 'telemetry' extra to export traces"
                )
            except Exception:
                logger.exception("OpenTelemetry exporter initialization failed")

        self._tracer = trace.get_tracer("mcp_guard.gateway")

    def span(
        self, name: str, attributes: dict[str, str | int | float | bool] | None = None
    ) -> AbstractContextManager[Any]:
        """Return a tracing span or a no-op context manager."""
        if self._tracer is None:
            return nullcontext()
        return cast(
            AbstractContextManager[Any],
            self._tracer.start_as_current_span(name, attributes=attributes or {}),
        )

    def shutdown(self) -> None:
        """Flush an exporter created by this gateway instance."""
        if self._owned_provider is not None:
            try:
                self._owned_provider.shutdown()
            except Exception:
                logger.exception("OpenTelemetry exporter shutdown failed")
