"""Admin API routes – require admin token."""
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.admin_auth import require_admin
from app.models.schemas import (
    ClientCreate, ClientUpdate, ClientResponse, ClientCreateResponse,
    PolicyCreate, PolicyUpdate, PolicyResponse,
    AdminLoginRequest, AdminLoginResponse,
)
from app.clients.service import (
    create_client, list_clients, get_client, update_client, delete_client
)
from app.policies.service import (
    create_policy, list_policies, get_policy, update_policy, delete_policy
)
from app.analytics.service import (
    get_overview, get_time_series, get_route_stats, get_client_stats, get_algo_stats
)
from app.redis.client import ping_redis
from app.config.settings import settings
import httpx

router = APIRouter(prefix="/admin/api/v1")

_start_time = time.time()


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=AdminLoginResponse, tags=["auth"])
async def admin_login(body: AdminLoginRequest):
    if body.token != settings.admin_token:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
    return AdminLoginResponse(access_token=settings.admin_token)


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get("/overview", tags=["analytics"], dependencies=[Depends(require_admin)])
async def overview(window: int = Query(default=3600, ge=60, le=86400)):
    return await get_overview(window)


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics", tags=["analytics"], dependencies=[Depends(require_admin)])
async def analytics(window: int = Query(default=3600, ge=60, le=86400)):
    ts      = await get_time_series(window)
    routes  = await get_route_stats(window)
    clients = await get_client_stats(window)
    algos   = await get_algo_stats(window)
    return {
        "time_series":  ts,
        "by_route":     routes,
        "by_client":    clients,
        "by_algorithm": algos,
    }


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["health"])
async def health():
    redis_ok, redis_ms = await ping_redis()

    # Check demo backend
    backend_ok  = False
    backend_ms  = 0.0
    backend_msg = ""
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(settings.demo_backend_url + "/api/health")
        backend_ok = r.status_code == 200
        backend_ms = (time.monotonic() - t0) * 1000
    except Exception as e:
        backend_msg = str(e)

    services = [
        {
            "name":       "redis",
            "status":     "healthy" if redis_ok else "down",
            "latency_ms": round(redis_ms, 2),
        },
        {
            "name":       "demo_backend",
            "status":     "healthy" if backend_ok else "down",
            "latency_ms": round(backend_ms, 2),
            "detail":     backend_msg or None,
        },
        {
            "name":   f"gateway ({settings.gateway_id})",
            "status": "healthy",
        },
    ]

    overall = "healthy" if redis_ok and backend_ok else "degraded"
    return {
        "overall":         overall,
        "gateway_id":      settings.gateway_id,
        "uptime_seconds":  round(time.time() - _start_time, 1),
        "services":        services,
    }


# ── Clients ───────────────────────────────────────────────────────────────────

@router.get("/clients", tags=["clients"], dependencies=[Depends(require_admin)])
async def list_clients_route():
    return await list_clients()


@router.post("/clients", tags=["clients"], dependencies=[Depends(require_admin)])
async def create_client_route(body: ClientCreate):
    result = await create_client(body)
    return result   # includes api_key (shown once)


@router.patch("/clients/{client_id}", tags=["clients"], dependencies=[Depends(require_admin)])
async def update_client_route(client_id: str, body: ClientUpdate):
    result = await update_client(client_id, body)
    if not result:
        raise HTTPException(status_code=404, detail={"error": "client_not_found"})
    return result


@router.delete("/clients/{client_id}", tags=["clients"], dependencies=[Depends(require_admin)])
async def delete_client_route(client_id: str):
    ok = await delete_client(client_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "client_not_found"})
    return {"deleted": True}


# ── Policies ──────────────────────────────────────────────────────────────────

@router.get("/policies", tags=["policies"], dependencies=[Depends(require_admin)])
async def list_policies_route():
    return await list_policies()


@router.post("/policies", tags=["policies"], dependencies=[Depends(require_admin)])
async def create_policy_route(body: PolicyCreate):
    return await create_policy(body)


@router.put("/policies/{policy_id}", tags=["policies"], dependencies=[Depends(require_admin)])
async def update_policy_route(policy_id: str, body: PolicyUpdate):
    result = await update_policy(policy_id, body)
    if not result:
        raise HTTPException(status_code=404, detail={"error": "policy_not_found"})
    return result


@router.delete("/policies/{policy_id}", tags=["policies"], dependencies=[Depends(require_admin)])
async def delete_policy_route(policy_id: str):
    ok = await delete_policy(policy_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "policy_not_found"})
    return {"deleted": True}
