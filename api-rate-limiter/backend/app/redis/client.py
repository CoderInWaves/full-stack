import redis.asyncio as aioredis
from app.config.settings import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:  # type: ignore
    global _redis
    if _redis is None:
        kwargs = {"encoding": "utf-8", "decode_responses": True}
        if settings.redis_password:
            kwargs["password"] = settings.redis_password
        _redis = await aioredis.from_url(settings.redis_url, **kwargs)
        logger.info("Redis connection established")
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis connection closed")


async def ping_redis():
    """Returns (ok, latency_ms)."""
    import time
    try:
        r = await get_redis()
        t0 = time.monotonic()
        await r.ping()
        return True, (time.monotonic() - t0) * 1000
    except Exception as e:
        logger.warning(f"Redis ping failed: {e}")
        return False, 0.0
