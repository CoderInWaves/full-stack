"""Reverse proxy: forwards allowed requests to the demo backend."""
import httpx
import logging
from fastapi import Request, Response
from app.config.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Headers we do NOT forward upstream
_HOP_BY_HOP = {
    "host", "connection", "transfer-encoding", "te",
    "trailer", "upgrade", "proxy-authorization", "proxy-authenticate",
}


async def proxy_request(request: Request) -> Response:
    """Forward the request to the demo backend and return its response."""
    target_url = settings.demo_backend_url.rstrip("/") + request.url.path
    if request.url.query:
        target_url += "?" + request.url.query

    # Filter headers
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
    headers["X-Forwarded-Proto"] = request.url.scheme

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )

        # Build response, strip hop-by-hop from upstream
        resp_headers = {
            k: v for k, v in upstream.headers.items()
            if k.lower() not in _HOP_BY_HOP
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )

    except httpx.ConnectError:
        logger.error(f"Cannot connect to backend: {settings.demo_backend_url}")
        return Response(
            content=b'{"error":"backend_unavailable","message":"Demo backend is not reachable"}',
            status_code=502,
            media_type="application/json",
        )
    except httpx.TimeoutException:
        logger.error("Backend request timed out")
        return Response(
            content=b'{"error":"backend_timeout","message":"Demo backend timed out"}',
            status_code=504,
            media_type="application/json",
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return Response(
            content=b'{"error":"proxy_error","message":"An unexpected error occurred"}',
            status_code=500,
            media_type="application/json",
        )
