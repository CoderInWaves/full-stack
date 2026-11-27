"""In-process Streamable HTTP benchmark for MCP-Guard.

Usage:
    python -m tests.benchmark --iterations 1000 --concurrency 1,8,32

It compares direct HTTPX requests to a mock upstream with requests sent through
the MCP-Guard ASGI app. It does not measure real network or server latency.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import math
import tempfile
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from mcp_guard.core.models import (
    AgentIdentity,
    AgentPolicy,
    DLPMode,
    DLPPattern,
    GatewayConfig,
    HTTPTransportConfig,
    IdentityConfig,
    LoggingConfig,
    PolicyAction,
    PolicyConfig,
    SecurityConfig,
    ServerPolicy,
    STDIOTransportConfig,
    ToolPolicy,
    UpstreamConfig,
)
from mcp_guard.transports.http import CURRENT_PROTOCOL_VERSION, HTTPTransport

UPSTREAM_URL = "http://upstream.test/mcp"
GATEWAY_URL = "http://gateway.test/mcp"
CLIENT_TOKEN = "benchmark-client-token"
UPSTREAM_TOKEN = "benchmark-upstream-token"


def make_config(log_file: str) -> GatewayConfig:
    return GatewayConfig(
        name="Benchmark",
        transport="http",
        stdio=STDIOTransportConfig(upstream=UpstreamConfig(name="bench_server", command=["echo"])),
        http=HTTPTransportConfig(
            upstream_url=UPSTREAM_URL,
            upstream_headers={"Authorization": f"Bearer {UPSTREAM_TOKEN}"},
        ),
        identity=IdentityConfig(
            agents={
                "bench": AgentIdentity(
                    id="bench-agent",
                    name="Benchmark Agent",
                    enabled=True,
                    servers=["bench_server"],
                    api_key_hash=hashlib.sha256(CLIENT_TOKEN.encode()).hexdigest(),
                )
            }
        ),
        policy=PolicyConfig(
            default_action=PolicyAction.DENY,
            agents={
                "bench-agent": AgentPolicy(
                    servers={
                        "bench_server": ServerPolicy(
                            enabled=True,
                            tools={
                                "fast_tool": ToolPolicy(action=PolicyAction.ALLOW),
                            },
                        )
                    }
                )
            },
        ),
        logging=LoggingConfig(file=log_file),
        security=SecurityConfig(
            enable_dlp=True,
            dlp_patterns=[
                DLPPattern(
                    name="email",
                    pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                    mode=DLPMode.REDACT,
                    replacement="[REDACTED]",
                ),
            ],
        ),
        upstreams={"bench_server": UpstreamConfig(name="bench_server", url=UPSTREAM_URL)},
    )


def _modern_request(request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "fast_tool",
            "arguments": {"value": "benchmark"},
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": CURRENT_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "benchmark", "version": "1"},
            },
        },
    }


def _request_headers(auth_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": CURRENT_PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "fast_tool",
    }


async def _measure(
    operation: Callable[[int], Awaitable[Any]],
    iterations: int,
    concurrency: int,
) -> tuple[list[float], float]:
    samples: list[float] = []
    worker_count = min(iterations, concurrency)
    base, remainder = divmod(iterations, worker_count)
    counts = [base + (1 if index < remainder else 0) for index in range(worker_count)]
    request_id = 0

    async def worker(count: int) -> list[float]:
        nonlocal request_id
        results = []
        for _ in range(count):
            request_id += 1
            started = time.perf_counter_ns()
            await operation(request_id)
            results.append((time.perf_counter_ns() - started) / 1_000_000)
        return results

    started = time.perf_counter()
    batches = await asyncio.gather(*(worker(count) for count in counts))
    elapsed = time.perf_counter() - started
    for batch in batches:
        samples.extend(batch)
    return samples, elapsed


async def _measure_peak_memory(
    operation: Callable[[int], Awaitable[Any]],
    iterations: int,
    concurrency: int,
) -> int:
    """Measure warmed, incremental Python allocations separately from timings."""
    for request_id in range(1, max(10, concurrency * 2) + 1):
        await operation(request_id)
    gc.collect()
    worker_count = min(iterations, concurrency)
    base, remainder = divmod(iterations, worker_count)
    counts = [base + (1 if index < remainder else 0) for index in range(worker_count)]
    request_id = 0

    async def worker(count: int) -> None:
        nonlocal request_id
        for _ in range(count):
            request_id += 1
            await operation(request_id)

    tracemalloc.start()
    try:
        baseline_bytes, _ = tracemalloc.get_traced_memory()
        await asyncio.gather(*(worker(count) for count in counts))
        _, peak_bytes = tracemalloc.get_traced_memory()
        return max(0, peak_bytes - baseline_bytes)
    finally:
        tracemalloc.stop()


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _report(
    label: str, samples: list[float], elapsed: float, peak_bytes: int, workers: int
) -> None:
    throughput = len(samples) / elapsed if elapsed else 0.0
    print(  # noqa: T201 -- command-line benchmark report
        f"{label:<13} {workers:>4} {len(samples):>7} "
        f"{_percentile(samples, 0.50):>9.3f} {_percentile(samples, 0.95):>9.3f} "
        f"{_percentile(samples, 0.99):>9.3f} {throughput:>11.1f} {peak_bytes:>11,}"
    )


async def benchmark(iterations: int, concurrency: list[int]) -> None:
    with tempfile.TemporaryDirectory(prefix="mcp-guard-bench-") as temp_dir:
        config = make_config(f"{temp_dir}/audit.jsonl")

        def upstream_handler(request: httpx.Request) -> httpx.Response:
            request_body = json.loads(request.content)
            result = {
                "jsonrpc": "2.0",
                "id": request_body["id"],
                "result": {"content": [{"type": "text", "text": "Contact benchmark@example.com"}]},
            }
            return httpx.Response(200, json=result)

        direct_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
        gateway = HTTPTransport(config)
        gateway._http_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream_handler))
        gateway_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.create_app()),
            base_url="http://gateway.test",
        )

        async def direct_call(request_id: int) -> httpx.Response:
            response = await direct_client.post(
                UPSTREAM_URL,
                headers=_request_headers(UPSTREAM_TOKEN),
                json=_modern_request(request_id),
            )
            await response.aread()
            return response

        async def guarded_call(request_id: int) -> httpx.Response:
            response = await gateway_client.post(
                "/mcp",
                headers=_request_headers(CLIENT_TOKEN),
                json=_modern_request(request_id),
            )
            await response.aread()
            return response

        print(  # noqa: T201 -- command-line benchmark report
            f"Requests per path: {iterations}; worker counts: {','.join(map(str, concurrency))}\n"
            "Direct = HTTPX to mock upstream; Guarded = HTTPX → MCP-Guard ASGI → mock upstream."
        )
        print(  # noqa: T201 -- command-line benchmark report
            f"{'Path':<13} {'Conc':>4} {'Ops':>7} {'p50 ms':>9} {'p95 ms':>9} "
            f"{'p99 ms':>9} {'ops/sec':>11} {'peak bytes':>11}"
        )

        try:
            for workers in concurrency:
                direct_timing = await _measure(direct_call, iterations, workers)
                direct_peak = await _measure_peak_memory(direct_call, iterations, workers)
                guarded_timing = await _measure(guarded_call, iterations, workers)
                guarded_peak = await _measure_peak_memory(guarded_call, iterations, workers)
                direct = (*direct_timing, direct_peak)
                guarded = (*guarded_timing, guarded_peak)
                _report("Direct", *direct, workers)
                _report("Guarded", *guarded, workers)
                extra = _percentile(guarded[0], 0.50) - _percentile(direct[0], 0.50)
                print(f"  Additional proxy p50 at concurrency {workers}: {extra:.3f} ms")  # noqa: T201
        finally:
            await gateway_client.aclose()
            await direct_client.aclose()
            await gateway.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations", type=int, default=1000, help="requests per path and worker count"
    )
    parser.add_argument(
        "--concurrency",
        default="1,8,32",
        help="comma-separated worker counts (for example: 1,8,32)",
    )
    args = parser.parse_args()
    if args.iterations <= 0:
        parser.error("--iterations must be positive")
    try:
        args.concurrency = [int(value) for value in args.concurrency.split(",")]
    except ValueError:
        parser.error("--concurrency must be a comma-separated list of positive integers")
    if not args.concurrency or any(value <= 0 for value in args.concurrency):
        parser.error("--concurrency must contain positive integers")
    return args


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(benchmark(args.iterations, args.concurrency))
