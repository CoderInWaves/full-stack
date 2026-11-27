"""Dependency-free Prometheus text metrics with bounded label values."""

from __future__ import annotations

import threading
from collections import defaultdict

METHOD_LABELS = {
    "initialize",
    "ping",
    "server/discover",
    "tools/list",
    "tools/call",
    "resources/list",
    "resources/read",
    "resources/templates/list",
    "prompts/list",
    "prompts/get",
    "tasks/get",
    "tasks/update",
    "tasks/cancel",
    "subscriptions/listen",
    "other",
}
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class MetricsRegistry:
    """Small in-process counters and latency histogram for Prometheus scrapes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str], int] = defaultdict(int)
        self._latency_count: dict[str, int] = defaultdict(int)
        self._latency_sum: dict[str, float] = defaultdict(float)
        self._latency_buckets: dict[tuple[str, float], int] = defaultdict(int)
        self._upstream_failures = 0
        self._authentication_failures = 0
        self._dlp_blocks = 0

    def record_request(
        self, method: str, decision: str, latency_ms: float, reason_code: str = ""
    ) -> None:
        method_label = method if method in METHOD_LABELS else "other"
        decision_label = {
            "ALLOW": "allowed",
            "DENY": "denied",
            "APPROVAL_REQUIRED": "approval_required",
            "REDACT": "redacted",
        }.get(decision, "other")
        seconds = max(latency_ms, 0.0) / 1000
        with self._lock:
            self._requests[(method_label, decision_label)] += 1
            self._latency_count[method_label] += 1
            self._latency_sum[method_label] += seconds
            for bound in LATENCY_BUCKETS:
                if seconds <= bound:
                    self._latency_buckets[(method_label, bound)] += 1
            if reason_code == "DLP_BLOCKED":
                self._dlp_blocks += 1

    def record_authentication_failure(self) -> None:
        with self._lock:
            self._authentication_failures += 1

    def record_upstream_failure(self) -> None:
        with self._lock:
            self._upstream_failures += 1

    def record_dlp_block(self) -> None:
        with self._lock:
            self._dlp_blocks += 1

    def render(self) -> str:
        """Render a Prometheus exposition document without sensitive labels."""
        with self._lock:
            lines = [
                "# HELP mcp_guard_requests_total MCP requests by bounded method and decision.",
                "# TYPE mcp_guard_requests_total counter",
            ]
            for (method, decision), value in sorted(self._requests.items()):
                lines.append(
                    f'mcp_guard_requests_total{{method="{method}",decision="{decision}"}} {value}'
                )
            lines.extend(
                [
                    "# HELP mcp_guard_request_duration_seconds MCP request duration.",
                    "# TYPE mcp_guard_request_duration_seconds histogram",
                ]
            )
            for method in sorted(self._latency_count):
                for bound in LATENCY_BUCKETS:
                    count = self._latency_buckets[(method, bound)]
                    lines.append(
                        f'mcp_guard_request_duration_seconds_bucket{{method="{method}",le="{bound:g}"}} {count}'
                    )
                lines.append(
                    f'mcp_guard_request_duration_seconds_bucket{{method="{method}",le="+Inf"}} {self._latency_count[method]}'
                )
                lines.append(
                    f'mcp_guard_request_duration_seconds_sum{{method="{method}"}} {self._latency_sum[method]:.9f}'
                )
                lines.append(
                    f'mcp_guard_request_duration_seconds_count{{method="{method}"}} {self._latency_count[method]}'
                )
            lines.extend(
                [
                    "# HELP mcp_guard_upstream_failures_total Upstream transport failures.",
                    "# TYPE mcp_guard_upstream_failures_total counter",
                    f"mcp_guard_upstream_failures_total {self._upstream_failures}",
                    "# HELP mcp_guard_authentication_failures_total Rejected authentication attempts.",
                    "# TYPE mcp_guard_authentication_failures_total counter",
                    f"mcp_guard_authentication_failures_total {self._authentication_failures}",
                    "# HELP mcp_guard_dlp_blocks_total Requests or responses blocked by DLP.",
                    "# TYPE mcp_guard_dlp_blocks_total counter",
                    f"mcp_guard_dlp_blocks_total {self._dlp_blocks}",
                ]
            )
            return "\n".join(lines) + "\n"
