"""Policy CRUD and lookup backed by Redis."""
import json
import time
import uuid
import logging
from app.redis.client import get_redis
from app.models.schemas import PolicyCreate, PolicyUpdate

logger = logging.getLogger(__name__)

POLICIES_HASH = "policies:registry"


async def create_policy(data: PolicyCreate) -> dict:
    redis = await get_redis()
    policy_id = "policy_" + uuid.uuid4().hex[:12]
    policy = {
        "id":              policy_id,
        "client_id":       data.client_id,
        "method":          data.method,
        "route":           data.route,
        "algorithm":       data.algorithm,
        "limit":           data.limit,
        "window":          data.window,
        "bucket_capacity": data.bucket_capacity,
        "refill_rate":     data.refill_rate,
        "enabled":         data.enabled,
        "created_at":      time.time(),
        "updated_at":      time.time(),
    }
    await redis.hset(POLICIES_HASH, policy_id, json.dumps(policy))
    logger.info(f"Created policy {policy_id}")
    return policy


async def list_policies() -> list:
    redis = await get_redis()
    raw = await redis.hvals(POLICIES_HASH)
    return [json.loads(r) for r in raw]


async def get_policy(policy_id: str):
    redis = await get_redis()
    raw = await redis.hget(POLICIES_HASH, policy_id)
    return json.loads(raw) if raw else None


async def update_policy(policy_id: str, data: PolicyUpdate):
    redis = await get_redis()
    raw = await redis.hget(POLICIES_HASH, policy_id)
    if not raw:
        return None
    policy = json.loads(raw)
    for field in ("algorithm", "limit", "window", "bucket_capacity", "refill_rate", "enabled"):
        val = getattr(data, field, None)
        if val is not None:
            policy[field] = val
    policy["updated_at"] = time.time()
    await redis.hset(POLICIES_HASH, policy_id, json.dumps(policy))
    return policy


async def delete_policy(policy_id: str) -> bool:
    redis = await get_redis()
    deleted = await redis.hdel(POLICIES_HASH, policy_id)
    return deleted > 0


async def resolve_policy(client_id: str, method: str, route: str) -> dict:
    """
    Policy precedence:
    1. Exact client + method + route
    2. Client + route (any method)
    3. Client-level default (no route, no method)
    4. Global default (no client_id)
    5. Hard-coded fallback
    """
    policies = await list_policies()
    enabled  = [p for p in policies if p.get("enabled", True)]
    mu       = method.upper()

    # 1. Exact: client + method + route
    for p in enabled:
        pm = (p.get("method") or "").upper()
        if p.get("client_id") == client_id and pm == mu and p.get("route") == route:
            return p

    # 2. Client + route, any method
    for p in enabled:
        if p.get("client_id") == client_id and p.get("method") is None and p.get("route") == route:
            return p

    # 3. Client default (no route, no method)
    for p in enabled:
        if p.get("client_id") == client_id and p.get("method") is None and p.get("route") is None:
            return p

    # 4. Global default
    for p in enabled:
        if p.get("client_id") is None and p.get("method") is None and p.get("route") is None:
            return p

    # 5. Hard-coded fallback
    from app.config.settings import settings
    return {
        "algorithm":       settings.default_algorithm,
        "limit":           settings.default_limit,
        "window":          settings.default_window,
        "bucket_capacity": None,
        "refill_rate":     None,
    }


async def seed_default_policies():
    """Seed a global default policy if none exist."""
    redis = await get_redis()
    existing = await redis.hlen(POLICIES_HASH)
    if existing > 0:
        return
    from app.models.schemas import PolicyCreate, Algorithm
    await create_policy(PolicyCreate(algorithm=Algorithm.sliding_window, limit=10, window=60))
    logger.info("Seeded default policies")
