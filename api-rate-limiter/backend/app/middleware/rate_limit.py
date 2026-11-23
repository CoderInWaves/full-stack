"""Rate-limit middleware: authenticate → resolve policy → run algorithm → allow/reject."""
import time
import logging
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.auth.api_key import authenticate_request
from app.policies.service import resolve_policy
from app.limiter import get_limiter
from app.redis.client import get_redis
from app.analytics.service import record_request
from app.config.settings import settings

logger = logging.getLogger(__name__)

# Routes that bypass rate limiting (admin, health, docs)
BYPASS_PREFIXES = ("/admin", "/docs", "/openapi", "/redoc", "/health", "/favicon")


def _is_bypassed(path: str) -> bool:
    """Match internal route roots without exempting similarly named paths."""
    if path == "/openapi.json":
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in BYPASS_PREFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip rate limiting for admin/internal routes
        if _is_bypassed(path):
            return await call_next(request)

        t0 = time.monotonic()

        # 1. Authenticate
        try:
            client = await authenticate_request(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )
        except Exception:
            # Authentication depends on Redis. An infrastructure failure is not
            # an invalid credential and must not turn into an unhandled 500.
            logger.exception("API key authentication failed")
            return JSONResponse(
                status_code=503,
                content={"error": "authentication_service_unavailable"},
            )

        client_id = client["id"]

        # 2. Resolve policy
        try:
            policy = await resolve_policy(client_id, request.method, path)
        except Exception as e:
            logger.error(f"Policy resolution failed: {e}")
            if settings.fail_open:
                return await call_next(request)
            return JSONResponse(status_code=503, content={"error": "service_unavailable"})

        # 3. Run rate-limit algorithm
        try:
            redis   = await get_redis()
            limiter = get_limiter(policy["algorithm"], redis)
            result  = await limiter.allow(client_id, path, policy)
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            if settings.fail_open:
                response = await call_next(request)
                return response
            return JSONResponse(status_code=503, content={"error": "rate_limiter_unavailable"})

        latency_ms = (time.monotonic() - t0) * 1000

        # 4. Reject if over limit
        if not result.allowed:
            await record_request(
                client_id=client_id,
                route=path,
                method=request.method,
                algorithm=policy["algorithm"],
                allowed=False,
                latency_ms=latency_ms,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error":       "rate_limit_exceeded",
                    "message":     "Too many requests. Please try again later.",
                    "retry_after": result.retry_after,
                },
                headers={
                    "X-RateLimit-Limit":     str(result.limit),
                    "X-RateLimit-Remaining": str(result.remaining),
                    "X-RateLimit-Reset":     str(int(result.reset_at)),
                    "Retry-After":           str(result.retry_after),
                    "X-RateLimit-Algorithm": result.algorithm,
                },
            )

        # 5. Forward request
        response = await call_next(request)
        latency_ms = (time.monotonic() - t0) * 1000

        await record_request(
            client_id=client_id,
            route=path,
            method=request.method,
            algorithm=policy["algorithm"],
            allowed=True,
            latency_ms=latency_ms,
        )

        # Attach rate-limit headers to successful response
        response.headers["X-RateLimit-Limit"]     = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"]     = str(int(result.reset_at))
        response.headers["X-RateLimit-Algorithm"] = result.algorithm
        response.headers["X-Gateway-ID"]          = settings.gateway_id

        return response
