"""Fixed Window Counter – uses inline Lua via redis.eval (atomic, no preload needed)."""
import time
import math
from app.limiter.base import BaseRateLimiter
from app.models.schemas import RateLimitResult

_LUA = """
local key    = KEYS[1]
local limit  = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local count  = redis.call("INCR", key)
if count == 1 then redis.call("EXPIRE", key, window) end
local allowed = count <= limit and 1 or 0
return {count, limit, allowed}
"""


class FixedWindowLimiter(BaseRateLimiter):
    def __init__(self, redis):
        self._redis = redis

    def _window_key(self, client_id: str, route: str, window: int) -> str:
        bucket = math.floor(time.time() / window)
        return f"rl:fw:{client_id}:{route}:{bucket}"

    async def allow(self, client_id: str, route: str, policy: dict) -> RateLimitResult:
        limit  = policy["limit"]
        window = policy["window"]
        key    = self._window_key(client_id, route, window)

        res = await self._redis.eval(_LUA, 1, key, limit, window)

        count       = int(res[0])
        lim         = int(res[1])
        allowed     = int(res[2]) == 1
        remaining   = max(0, lim - count)
        bucket      = math.floor(time.time() / window)
        reset_at    = (bucket + 1) * window
        retry_after = max(0, int(reset_at - time.time())) if not allowed else 0

        return RateLimitResult(
            allowed=allowed,
            limit=lim,
            remaining=remaining,
            retry_after=retry_after,
            reset_at=reset_at,
            algorithm="fixed_window",
        )
