"""Factory: returns the correct limiter instance for a given algorithm name."""
from app.limiter.fixed_window import FixedWindowLimiter
from app.limiter.sliding_window import SlidingWindowLimiter
from app.limiter.token_bucket import TokenBucketLimiter
from app.limiter.base import BaseRateLimiter


def get_limiter(algorithm: str, redis) -> BaseRateLimiter:
    if algorithm == "fixed_window":
        return FixedWindowLimiter(redis)
    if algorithm == "sliding_window":
        return SlidingWindowLimiter(redis)
    if algorithm == "token_bucket":
        return TokenBucketLimiter(redis)
    raise ValueError(f"Unknown algorithm: {algorithm}")
