"""Common interface for all rate-limiting algorithms."""
from abc import ABC, abstractmethod
from app.models.schemas import RateLimitResult


class BaseRateLimiter(ABC):
    @abstractmethod
    async def allow(self, client_id: str, route: str, policy: dict) -> RateLimitResult:
        """
        Decide whether to allow a request.

        Args:
            client_id: Unique client identifier (hashed).
            route:     API route being accessed e.g. "/api/products".
            policy:    Dict with keys: limit, window, algorithm,
                       bucket_capacity, refill_rate.

        Returns:
            RateLimitResult with allowed, limit, remaining, retry_after, reset_at.
        """
        ...
