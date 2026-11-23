"""Analytics: time-bucketed counters stored in Redis."""
import time
import json
import logging
import math
from app.redis.client import get_redis
from app.config.settings import settings

logger = logging.getLogger(__name__)

BUCKET_SIZE   = 60          # 1-minute buckets
METRICS_TTL   = 86400       # keep 24 hours of data
LATENCY_KEY   = "analytics:latency:samples"
LATENCY_MAX   = 10000       # bounded ring buffer size


def _bucket(ts: float) -> int:
    return int(ts // BUCKET_SIZE) * BUCKET_SIZE


async def record_request(
    *,
    client_id: str,
    route: str,
    method: str,
    algorithm: str,
    allowed: bool,
    latency_ms: float,
):
    try:
        redis = await get_redis()
        now   = time.time()
        bkt   = _bucket(now)
        pipe  = redis.pipeline()

        # Time-series bucket
        bkt_key = f"analytics:ts:{bkt}"
        pipe.hincrby(bkt_key, "total", 1)
        pipe.hincrby(bkt_key, "allowed" if allowed else "rejected", 1)
        pipe.expire(bkt_key, METRICS_TTL)

        # Per-route
        route_key = f"analytics:route:{route}:{bkt}"
        pipe.hincrby(route_key, "total", 1)
        pipe.hincrby(route_key, "allowed" if allowed else "rejected", 1)
        pipe.expire(route_key, METRICS_TTL)

        # Per-client
        client_key = f"analytics:client:{client_id}:{bkt}"
        pipe.hincrby(client_key, "total", 1)
        pipe.hincrby(client_key, "rejected" if not allowed else "allowed", 1)
        pipe.expire(client_key, METRICS_TTL)

        # Per-algorithm
        algo_key = f"analytics:algo:{algorithm}:{bkt}"
        pipe.hincrby(algo_key, "total", 1)
        pipe.expire(algo_key, METRICS_TTL)

        # Latency samples (bounded sorted set: score=ts, member=latency:uuid)
        import uuid
        member = f"{latency_ms:.3f}:{uuid.uuid4().hex[:8]}"
        pipe.zadd(LATENCY_KEY, {member: now})
        pipe.zremrangebyrank(LATENCY_KEY, 0, -(LATENCY_MAX + 1))
        pipe.expire(LATENCY_KEY, METRICS_TTL)

        await pipe.execute()
    except Exception as e:
        logger.warning(f"Analytics record failed: {e}")


async def get_overview(window_seconds: int = 3600) -> dict:
    try:
        redis  = await get_redis()
        now    = time.time()
        start  = now - window_seconds
        buckets = range(int(_bucket(start)), int(_bucket(now)) + BUCKET_SIZE, BUCKET_SIZE)

        total = allowed = rejected = 0
        pipe = redis.pipeline()
        for bkt in buckets:
            pipe.hgetall(f"analytics:ts:{bkt}")
        results = await pipe.execute()

        for r in results:
            total    += int(r.get("total", 0))
            allowed  += int(r.get("allowed", 0))
            rejected += int(r.get("rejected", 0))

        rps = total / window_seconds if window_seconds > 0 else 0

        # Latency percentiles
        samples_raw = await redis.zrangebyscore(LATENCY_KEY, now - window_seconds, now)
        latencies = sorted([float(s.split(":")[0]) for s in samples_raw])
        avg_ms = p95_ms = p99_ms = 0.0
        if latencies:
            avg_ms = sum(latencies) / len(latencies)
            p95_ms = _percentile(latencies, 95)
            p99_ms = _percentile(latencies, 99)

        from app.clients.service import list_clients
        from app.policies.service import list_policies
        clients  = await list_clients()
        policies = await list_policies()

        return {
            "total_requests":    total,
            "allowed_requests":  allowed,
            "rejected_requests": rejected,
            "total_clients":     len(clients),
            "active_policies":   sum(1 for p in policies if p.get("enabled", True)),
            "requests_per_second": round(rps, 3),
            "avg_latency_ms":    round(avg_ms, 2),
            "p95_latency_ms":    round(p95_ms, 2),
            "p99_latency_ms":    round(p99_ms, 2),
        }
    except Exception as e:
        logger.warning(f"get_overview failed: {e}")
        return _empty_overview()


async def get_time_series(window_seconds: int = 3600) -> list[dict]:
    try:
        redis  = await get_redis()
        now    = time.time()
        start  = now - window_seconds
        series = []
        buckets = list(range(int(_bucket(start)), int(_bucket(now)) + BUCKET_SIZE, BUCKET_SIZE))

        pipe = redis.pipeline()
        for bkt in buckets:
            pipe.hgetall(f"analytics:ts:{bkt}")
        results = await pipe.execute()

        for bkt, r in zip(buckets, results):
            series.append({
                "timestamp": bkt,
                "total":     int(r.get("total", 0)),
                "allowed":   int(r.get("allowed", 0)),
                "rejected":  int(r.get("rejected", 0)),
            })
        return series
    except Exception as e:
        logger.warning(f"get_time_series failed: {e}")
        return []


async def get_route_stats(window_seconds: int = 3600) -> list[dict]:
    try:
        redis = await get_redis()
        now   = time.time()
        start = now - window_seconds
        buckets = list(range(int(_bucket(start)), int(_bucket(now)) + BUCKET_SIZE, BUCKET_SIZE))

        # Discover routes
        route_keys = await redis.keys("analytics:route:*")
        routes = set()
        for k in route_keys:
            parts = k.split(":")
            if len(parts) >= 3:
                routes.add(parts[2])

        stats = []
        for route in routes:
            total = allowed = rejected = 0
            pipe = redis.pipeline()
            for bkt in buckets:
                pipe.hgetall(f"analytics:route:{route}:{bkt}")
            results = await pipe.execute()
            for r in results:
                total    += int(r.get("total", 0))
                allowed  += int(r.get("allowed", 0))
                rejected += int(r.get("rejected", 0))
            if total > 0:
                stats.append({"route": route, "total": total, "allowed": allowed, "rejected": rejected})

        return sorted(stats, key=lambda x: x["total"], reverse=True)
    except Exception as e:
        logger.warning(f"get_route_stats failed: {e}")
        return []


async def get_client_stats(window_seconds: int = 3600) -> list[dict]:
    try:
        redis = await get_redis()
        now   = time.time()
        start = now - window_seconds
        buckets = list(range(int(_bucket(start)), int(_bucket(now)) + BUCKET_SIZE, BUCKET_SIZE))

        client_keys = await redis.keys("analytics:client:*")
        client_ids  = set()
        for k in client_keys:
            parts = k.split(":")
            if len(parts) >= 3:
                client_ids.add(parts[2])

        from app.clients.service import get_client
        stats = []
        for cid in client_ids:
            total = allowed = rejected = 0
            pipe = redis.pipeline()
            for bkt in buckets:
                pipe.hgetall(f"analytics:client:{cid}:{bkt}")
            results = await pipe.execute()
            for r in results:
                total    += int(r.get("total", 0))
                allowed  += int(r.get("allowed", 0))
                rejected += int(r.get("rejected", 0))
            if total > 0:
                client = await get_client(cid)
                name   = client["name"] if client else cid
                stats.append({"client_id": cid, "client_name": name, "total": total, "rejected": rejected})

        return sorted(stats, key=lambda x: x["total"], reverse=True)
    except Exception as e:
        logger.warning(f"get_client_stats failed: {e}")
        return []


async def get_algo_stats(window_seconds: int = 3600) -> dict:
    try:
        redis = await get_redis()
        now   = time.time()
        start = now - window_seconds
        buckets = list(range(int(_bucket(start)), int(_bucket(now)) + BUCKET_SIZE, BUCKET_SIZE))

        algo_keys = await redis.keys("analytics:algo:*")
        algos = set()
        for k in algo_keys:
            parts = k.split(":")
            if len(parts) >= 3:
                algos.add(parts[2])

        result = {}
        for algo in algos:
            total = 0
            pipe = redis.pipeline()
            for bkt in buckets:
                pipe.hgetall(f"analytics:algo:{algo}:{bkt}")
            results = await pipe.execute()
            for r in results:
                total += int(r.get("total", 0))
            result[algo] = total
        return result
    except Exception as e:
        logger.warning(f"get_algo_stats failed: {e}")
        return {}


def _percentile(sorted_data: list, pct: float) -> float:
    if not sorted_data:
        return 0.0
    # Nearest-rank percentile: rank = ceil(p * n), converted to zero-based.
    idx = math.ceil(len(sorted_data) * pct / 100) - 1
    idx = max(0, idx)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def _empty_overview() -> dict:
    return {
        "total_requests": 0, "allowed_requests": 0, "rejected_requests": 0,
        "total_clients": 0, "active_policies": 0, "requests_per_second": 0.0,
        "avg_latency_ms": 0.0, "p95_latency_ms": 0.0, "p99_latency_ms": 0.0,
    }
