"""Concurrency tests – 100 simultaneous requests, verify exact limit enforcement."""
import pytest
import asyncio
import redis.asyncio as aioredis

REDIS_URL = "redis://localhost:6379/2"


@pytest.fixture
async def r():
    client = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def _fire(limiter, client_id, route, policy, n):
    return await asyncio.gather(*[limiter.allow(client_id, route, policy) for _ in range(n)])


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_fixed_window_100_concurrent(self, r):
        from app.limiter.fixed_window import FixedWindowLimiter
        results = await _fire(FixedWindowLimiter(r), "cfw", "/api/t", {"limit": 10, "window": 60}, 100)
        assert sum(x.allowed for x in results) == 10

    @pytest.mark.asyncio
    async def test_sliding_window_100_concurrent(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        results = await _fire(SlidingWindowLimiter(r), "csw", "/api/t", {"limit": 10, "window": 60}, 100)
        assert sum(x.allowed for x in results) == 10

    @pytest.mark.asyncio
    async def test_token_bucket_100_concurrent(self, r):
        from app.limiter.token_bucket import TokenBucketLimiter
        policy  = {"limit": 10, "window": 60, "bucket_capacity": 10, "refill_rate": 0.1}
        results = await _fire(TokenBucketLimiter(r), "ctb", "/api/t", policy, 100)
        assert sum(x.allowed for x in results) == 10

    @pytest.mark.asyncio
    async def test_two_clients_independent(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(r)
        policy  = {"limit": 5, "window": 60}
        r1, r2  = await asyncio.gather(
            _fire(limiter, "clientA", "/api/t", policy, 10),
            _fire(limiter, "clientB", "/api/t", policy, 10),
        )
        assert sum(x.allowed for x in r1) == 5
        assert sum(x.allowed for x in r2) == 5

    @pytest.mark.asyncio
    async def test_shared_state_two_gateway_instances(self, r):
        """Two limiter instances sharing same Redis must not exceed combined limit."""
        from app.limiter.sliding_window import SlidingWindowLimiter
        l1, l2  = SlidingWindowLimiter(r), SlidingWindowLimiter(r)
        policy  = {"limit": 10, "window": 60}
        results = await asyncio.gather(
            *[l1.allow("shared", "/api/t", policy) for _ in range(50)],
            *[l2.allow("shared", "/api/t", policy) for _ in range(50)],
        )
        assert sum(x.allowed for x in results) == 10
