"""Token Bucket – Redis Hash + inline Lua (atomic)."""
import time
from app.limiter.base import BaseRateLimiter
from app.models.schemas import RateLimitResult

_LUA = """
local key         = KEYS[1]
local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local ttl         = tonumber(ARGV[3])
local now_arr     = redis.call("TIME")
local now         = tonumber(now_arr[1]) + tonumber(now_arr[2]) / 1000000
local data        = redis.call("HMGET", key, "tokens", "last_refill")
local tokens      = tonumber(data[1])
local last_refill = tonumber(data[2])
if tokens == nil then
    tokens      = capacity
    last_refill = now
end
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * refill_rate)
last_refill = now
local allowed = 0
if tokens >= 1 then
    tokens  = tokens - 1
    allowed = 1
end
redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
redis.call("EXPIRE", key, ttl)
return {allowed, math.floor(tokens), capacity}
"""


class TokenBucketLimiter(BaseRateLimiter):
    def __init__(self, redis):
        self._redis = redis

    def _key(self, client_id: str, route: str) -> str:
        return f"rl:tb:{client_id}:{route}"

    async def allow(self, client_id: str, route: str, policy: dict) -> RateLimitResult:
        capacity    = policy.get("bucket_capacity") or policy["limit"]
        refill_rate = policy.get("refill_rate") or (capacity / policy["window"])
        ttl         = policy["window"] * 2
        key         = self._key(client_id, route)

        res = await self._redis.eval(_LUA, 1, key, capacity, refill_rate, ttl)

        allowed     = int(res[0]) == 1
        tokens_left = int(res[1])
        cap         = int(res[2])
        remaining   = tokens_left
        retry_after = max(1, int(1.0 / refill_rate)) if not allowed and refill_rate > 0 else 0
        reset_at    = time.time() + (cap / refill_rate if refill_rate > 0 else 0)

        return RateLimitResult(
            allowed=allowed,
            limit=cap,
            remaining=remaining,
            retry_after=retry_after,
            reset_at=reset_at,
            algorithm="token_bucket",
        )
