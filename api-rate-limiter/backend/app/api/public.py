"""Public gateway routes – all protected by rate-limit middleware."""
from fastapi import APIRouter, Request
from app.proxy.reverse_proxy import proxy_request

router = APIRouter()


@router.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def gateway_proxy(request: Request, path: str):
    """Forward any /api/* request to the demo backend (after rate limiting)."""
    return await proxy_request(request)
