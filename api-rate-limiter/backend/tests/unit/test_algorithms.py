"""Unit tests for rate-limiting algorithms using mocked Redis."""
import pytest
import time
import math
from unittest.mock import AsyncMock, patch


def make_redis(return_value):
    r = AsyncMock()
    r.eval = AsyncMock(return_value=return_value)
    return r


# ── Fixed Window ──────────────────────────────────────────────────────────────

class TestFixedWindow:
    @pytest.mark.asyncio
    async def test_allows_first_request(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(make_redis([1, 10, 1]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.allowed is True
        assert result.limit == 10
        assert result.remaining == 9

    @pytest.mark.asyncio
    async def test_rejects_over_limit(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(make_redis([11, 10, 0]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_remaining_decrements(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(make_redis([5, 10, 1]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.remaining == 5

    @pytest.mark.asyncio
    async def test_reset_at_is_future(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(make_redis([1, 10, 1]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.reset_at > time.time()

    @pytest.mark.asyncio
    async def test_algorithm_label(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(make_redis([1, 10, 1]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.algorithm == "fixed_window"

    def test_window_key_includes_bucket(self):
        from app.limiter.fixed_window import FixedWindowLimiter
        limiter = FixedWindowLimiter(None)
        window  = 60
        key     = limiter._window_key("c1", "/api/products", window)
        bucket  = math.floor(time.time() / window)
        assert str(bucket) in key
        assert key.startswith("rl:fw:")


# ── Sliding Window ────────────────────────────────────────────────────────────

class TestSlidingWindow:
    def _now_ms(self):
        return int(time.time() * 1000)

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(make_redis([1, 3, 10, self._now_ms()]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.allowed is True
        assert result.remaining == 7

    @pytest.mark.asyncio
    async def test_rejects_at_limit(self):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(make_redis([0, 10, 10, self._now_ms()]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.allowed is False
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_retry_after_equals_window(self):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(make_redis([0, 10, 10, self._now_ms()]))
        result  = await limiter.allow("c1", "/api/products", {"limit": 10, "window": 60})
        assert result.retry_after == 60

    @pytest.mark.asyncio
    async def test_algorithm_label(self):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(make_redis([1, 1, 10, self._now_ms()]))
        result  = await limiter.allow("c1", "/api/x", {"limit": 10, "window": 60})
        assert result.algorithm == "sliding_window"

    def test_key_format(self):
        from app.limiter.sliding_window import SlidingWindowLimiter
        limiter = SlidingWindowLimiter(None)
        assert limiter._key("c1", "/api/products") == "rl:sw:c1:/api/products"


# ── Token Bucket ──────────────────────────────────────────────────────────────

class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_allows_when_tokens_available(self):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter = TokenBucketLimiter(make_redis([1, 9, 10]))
        result  = await limiter.allow("c1", "/api/products", {
            "limit": 10, "window": 60, "bucket_capacity": 10, "refill_rate": 1.0
        })
        assert result.allowed is True
        assert result.remaining == 9
        assert result.limit == 10

    @pytest.mark.asyncio
    async def test_rejects_when_no_tokens(self):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter = TokenBucketLimiter(make_redis([0, 0, 10]))
        result  = await limiter.allow("c1", "/api/products", {
            "limit": 10, "window": 60, "bucket_capacity": 10, "refill_rate": 1.0
        })
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after >= 1

    @pytest.mark.asyncio
    async def test_uses_limit_as_capacity_fallback(self):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter = TokenBucketLimiter(make_redis([1, 9, 10]))
        result  = await limiter.allow("c1", "/api/x", {
            "limit": 10, "window": 60, "bucket_capacity": None, "refill_rate": None
        })
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_algorithm_label(self):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter = TokenBucketLimiter(make_redis([1, 5, 10]))
        result  = await limiter.allow("c1", "/api/x", {
            "limit": 10, "window": 60, "bucket_capacity": 10, "refill_rate": 1.0
        })
        assert result.algorithm == "token_bucket"

    def test_key_format(self):
        from app.limiter.token_bucket import TokenBucketLimiter
        limiter = TokenBucketLimiter(None)
        assert limiter._key("c1", "/api/products") == "rl:tb:c1:/api/products"


# ── Policy Resolution ─────────────────────────────────────────────────────────

class TestPolicyResolution:
    @pytest.mark.asyncio
    async def test_exact_match_wins(self):
        from app.policies.service import resolve_policy
        policies = [
            {"id": "p1", "client_id": "c1", "method": "GET", "route": "/api/products",
             "algorithm": "fixed_window", "limit": 5, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": True},
            {"id": "p2", "client_id": None, "method": None, "route": None,
             "algorithm": "sliding_window", "limit": 100, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": True},
        ]
        with patch("app.policies.service.list_policies", AsyncMock(return_value=policies)):
            result = await resolve_policy("c1", "GET", "/api/products")
        assert result["limit"] == 5
        assert result["algorithm"] == "fixed_window"

    @pytest.mark.asyncio
    async def test_global_default_fallback(self):
        from app.policies.service import resolve_policy
        policies = [
            {"id": "p1", "client_id": None, "method": None, "route": None,
             "algorithm": "token_bucket", "limit": 20, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": True},
        ]
        with patch("app.policies.service.list_policies", AsyncMock(return_value=policies)):
            result = await resolve_policy("unknown", "POST", "/api/orders")
        assert result["limit"] == 20

    @pytest.mark.asyncio
    async def test_disabled_policy_skipped(self):
        from app.policies.service import resolve_policy
        from app.config.settings import settings
        policies = [
            {"id": "p1", "client_id": "c1", "method": "GET", "route": "/api/products",
             "algorithm": "fixed_window", "limit": 5, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": False},
        ]
        with patch("app.policies.service.list_policies", AsyncMock(return_value=policies)):
            result = await resolve_policy("c1", "GET", "/api/products")
        assert result["limit"] == settings.default_limit

    @pytest.mark.asyncio
    async def test_client_default_over_global(self):
        from app.policies.service import resolve_policy
        policies = [
            {"id": "p1", "client_id": "c1", "method": None, "route": None,
             "algorithm": "fixed_window", "limit": 50, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": True},
            {"id": "p2", "client_id": None, "method": None, "route": None,
             "algorithm": "sliding_window", "limit": 10, "window": 60,
             "bucket_capacity": None, "refill_rate": None, "enabled": True},
        ]
        with patch("app.policies.service.list_policies", AsyncMock(return_value=policies)):
            result = await resolve_policy("c1", "GET", "/api/anything")
        assert result["limit"] == 50


# ── API Key Auth ──────────────────────────────────────────────────────────────

class TestApiKeyAuth:
    def test_hash_is_deterministic(self):
        from app.auth.api_key import hash_api_key
        assert hash_api_key("test_key") == hash_api_key("test_key")

    def test_different_keys_different_hashes(self):
        from app.auth.api_key import hash_api_key
        assert hash_api_key("key_a") != hash_api_key("key_b")

    def test_generated_key_has_prefix(self):
        from app.auth.api_key import generate_api_key
        assert generate_api_key().startswith("rlk_")

    def test_generated_key_length(self):
        from app.auth.api_key import generate_api_key
        assert len(generate_api_key()) > 20

    def test_hash_not_equal_to_raw(self):
        from app.auth.api_key import generate_api_key, hash_api_key
        key = generate_api_key()
        assert hash_api_key(key) != key

    def test_two_generated_keys_are_unique(self):
        from app.auth.api_key import generate_api_key
        assert generate_api_key() != generate_api_key()


class TestAnalyticsHelpers:
    def test_percentile_uses_nearest_rank_for_small_samples(self):
        from app.analytics.service import _percentile
        assert _percentile([10, 20, 30, 40], 95) == 40
        assert _percentile([10, 20, 30, 40], 50) == 20

    def test_percentile_handles_empty_and_single_samples(self):
        from app.analytics.service import _percentile
        assert _percentile([], 95) == 0
        assert _percentile([7], 99) == 7


class TestMiddlewareBypassMatching:
    @pytest.mark.parametrize("path", ["/admin", "/admin/api/v1/health", "/health", "/docs", "/openapi.json"])
    def test_internal_roots_are_bypassed(self, path):
        from app.middleware.rate_limit import _is_bypassed
        assert _is_bypassed(path)

    @pytest.mark.parametrize("path", ["/administrator", "/healthcheck", "/docs-private", "/api/admin"])
    def test_similar_public_paths_are_not_bypassed(self, path):
        from app.middleware.rate_limit import _is_bypassed
        assert not _is_bypassed(path)
