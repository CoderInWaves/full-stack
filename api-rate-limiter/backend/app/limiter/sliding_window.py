"""Sliding Window Log – Redis Sorted Set + inline Lua (atomic)."""
import time
import uuid
from app.limiter.base import BaseRateLimiter
from app.models.schemas import RateLimitResult

_LUA = """
local key       = KEYS[1]
local limit     = tonumber(ARGV[1])
local window    = tonumber(ARGV[2])
local req_id    = ARGV[3]
local now_arr   = redis.call("TIME")
local now_ms    = tonumber(now_arr[1]) * 1000 + math.floor(tonumber(now_arr[2]) / 1000)
local cutoff_ms = now_ms - window * 1000
redis.call("ZREMRANGEBYSCORE", key, "-inf", cutoff_ms)
local count = redis.call("ZCARD", key)
local allowed = 0
if count < limit then
    redis.call("ZADD", key, now_ms, now_ms .. ":" .. req_id)
    redis.call("PEXPIRE", key, window * 1000 + 1000)
    allowed = 1
    count = count + 1
end
return {allowed, count, limit, now_ms}
"""


class SlidingWindowLimiter(BaseRateLimiter):
    def __init__(self, redis):
        self._redis = redis

    def _key(self, client_id: str, route: str) -> str:
        return f"rl:sw:{client_id}:{route}"

    async def allow(self, client_id: str, route: str, policy: dict) -> RateLimitResult:
        limit  = policy["limit"]
        window = policy["window"]
        key    = self._key(client_id, route)
        req_id = uuid.uuid4().hex[:12]

        res = await self._redis.eval(_LUA, 1, key, limit, window, req_id)

        allowed   = int(res[0]) == 1
        count     = int(res[1])
        lim       = int(res[2])
        now_ms    = float(res[3])
        remaining = max(0, lim - count)
        reset_at  = now_ms / 1000.0 + window
        retry_after = window if not allowed else 0

        return RateLimitResult(
            allowed=allowed,
            limit=lim,
            remaining=remaining,
            retry_after=retry_after,
            reset_at=reset_at,
            algorithm="sliding_window",
        )
