"""FastAPI Gateway – entry point."""
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.redis.client import get_redis, close_redis
from app.redis.scripts import load_scripts
from app.middleware.rate_limit import RateLimitMiddleware
from app.api.public import router as public_router
from app.api.admin import router as admin_router
from app.clients.service import seed_dev_clients
from app.policies.service import seed_default_policies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting gateway {settings.gateway_id}")
    redis = await get_redis()
    await load_scripts(redis)
    await seed_dev_clients()
    await seed_default_policies()
    logger.info("Gateway ready")
    yield
    # Shutdown
    await close_redis()
    logger.info("Gateway shut down")


app = FastAPI(
    title="Distributed API Rate Limiter – Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
        "X-RateLimit-Algorithm",
        "X-Gateway-ID",
    ],
)

# Rate-limit middleware (applied to all routes except bypassed prefixes)
app.add_middleware(RateLimitMiddleware)

# Routers
app.include_router(public_router)
app.include_router(admin_router)


@app.get("/health", tags=["health"])
async def gateway_health():
    return {"status": "healthy", "gateway_id": settings.gateway_id, "ts": time.time()}
