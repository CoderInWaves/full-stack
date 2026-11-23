"""Integration tests – require a real Redis on localhost:6379."""
import pytest
import asyncio
import redis.asyncio as aioredis

REDIS_URL = "redis://localhost:6379/1"


@pytest.fixture
async def r():
    client = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


class TestFixedWindowIntegration:
    @pytest.mark.asyncio
    async def test_allows_up_to_limit(self, r):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter  = FixedWindowLimiter(r)
        policy   = {"limit": 5, "window": 60}
        results  = [await limiter.allow("ifw1", "/api/t", policy) for _ in range(5)]
        assert all(x.allowed for x in results)

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self, r):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter  = FixedWindowLimiter(r)
        policy   = {"limit": 3, "window": 60}
        results  = [await limiter.allow("ifw2", "/api/t", policy) for _ in range(6)]
        assert sum(x.allowed for x in results) == 3

    @pytest.mark.asyncio
    async def test_window_resets(self, r):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter  = FixedWindowLimiter(r)
        policy   = {"limit": 2, "window": 1}
        await limiter.allow("ifw3", "/api/t", policy)
        await limiter.allow("ifw3", "/api/t", policy)
        assert not (await limiter.allow("ifw3", "/api/t", policy)).allowed
        await asyncio.sleep(1.1)
        assert (await limiter.allow("ifw3", "/api/t", policy)).allowed


class TestSlidingWindowIntegration:
    @pytest.mark.asyncio
    async def test_allows_up_to_limit(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter  = SlidingWindowLimiter(r)
        policy   = {"limit": 5, "window": 60}
        results  = [await limiter.allow("isw1", "/api/t", policy) for _ in range(5)]
        assert all(x.allowed for x in results)

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter  = SlidingWindowLimiter(r)
        policy   = {"limit": 3, "window": 60}
        results  = [await limiter.allow("isw2", "/api/t", policy) for _ in range(6)]
        assert sum(x.allowed for x in results) == 3

    @pytest.mark.asyncio
    async def test_old_entries_expire(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter  = SlidingWindowLimiter(r)
        policy   = {"limit": 2, "window": 1}
        await limiter.allow("isw3", "/api/t", policy)
        await limiter.allow("isw3", "/api/t", policy)
        assert not (await limiter.allow("isw3", "/api/t", policy)).allowed
        await asyncio.sleep(1.1)
        assert (await limiter.allow("isw3", "/api/t", policy)).allowed

    @pytest.mark.asyncio
    async def test_uses_sorted_set(self, r):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter  = SlidingWindowLimiter(r)
        await limiter.allow("isw4", "/api/t", {"limit": 5, "window": 60})
        keys = await r.keys("rl:sw:*")
        assert len(keys) > 0


class TestTokenBucketIntegration:
    @pytest.mark.asyncio
    async def test_full_bucket_allows(self, r):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter  = TokenBucketLimiter(r)
        policy   = {"limit": 5, "window": 60, "bucket_capacity": 5, "refill_rate": 1.0}
        results  = [await limiter.allow("itb1", "/api/t", policy) for _ in range(5)]
        assert all(x.allowed for x in results)

    @pytest.mark.asyncio
    async def test_empty_bucket_rejects(self, r):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter  = TokenBucketLimiter(r)
        policy   = {"limit": 3, "window": 60, "bucket_capacity": 3, "refill_rate": 0.1}
        results  = [await limiter.allow("itb2", "/api/t", policy) for _ in range(5)]
        assert sum(x.allowed for x in results) == 3

    @pytest.mark.asyncio
    async def test_refill_over_time(self, r):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter  = TokenBucketLimiter(r)
        policy   = {"limit": 2, "window": 60, "bucket_capacity": 2, "refill_rate": 5.0}
        await limiter.allow("itb3", "/api/t", policy)
        await limiter.allow("itb3", "/api/t", policy)
        assert not (await limiter.allow("itb3", "/api/t", policy)).allowed
        await asyncio.sleep(0.3)   # 0.3s × 5 tokens/s = 1.5 tokens refilled
        assert (await limiter.allow("itb3", "/api/t", policy)).allowed
