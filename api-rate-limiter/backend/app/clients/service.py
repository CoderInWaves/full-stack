"""Client CRUD operations backed by Redis."""
import json
import time
import uuid
import logging
from app.redis.client import get_redis
from app.auth.api_key import generate_api_key, hash_api_key
from app.models.schemas import ClientCreate, ClientUpdate

logger = logging.getLogger(__name__)

CLIENTS_HASH = "clients:registry"       # client_id → JSON
KEY_HASH_MAP  = "clients:by_key_hash"   # key_hash  → JSON (same client data)


async def create_client(data: ClientCreate) -> dict:
    redis = await get_redis()
    client_id = "client_" + uuid.uuid4().hex[:12]
    raw_key   = generate_api_key()
    key_hash  = hash_api_key(raw_key)

    client = {
        "id":          client_id,
        "name":        data.name,
        "tier":        data.tier,
        "enabled":     True,
        "created_at":  time.time(),
        "key_hash":    key_hash,
        "key_prefix":  raw_key[:8],
    }

    pipe = redis.pipeline()
    pipe.hset(CLIENTS_HASH, client_id, json.dumps(client))
    pipe.hset(KEY_HASH_MAP, key_hash, json.dumps(client))
    await pipe.execute()

    logger.info(f"Created client {client_id} ({data.name})")
    return {**client, "api_key": raw_key}


async def list_clients() -> list[dict]:
    redis = await get_redis()
    raw = await redis.hvals(CLIENTS_HASH)
    return [json.loads(r) for r in raw]


async def get_client(client_id: str):  # -> dict | None
    redis = await get_redis()
    raw = await redis.hget(CLIENTS_HASH, client_id)
    return json.loads(raw) if raw else None


async def update_client(client_id: str, data: ClientUpdate):  # -> dict | None
    redis = await get_redis()
    raw = await redis.hget(CLIENTS_HASH, client_id)
    if not raw:
        return None
    client = json.loads(raw)

    if data.name is not None:
        client["name"] = data.name
    if data.tier is not None:
        client["tier"] = data.tier
    if data.enabled is not None:
        client["enabled"] = data.enabled

    pipe = redis.pipeline()
    pipe.hset(CLIENTS_HASH, client_id, json.dumps(client))
    pipe.hset(KEY_HASH_MAP, client["key_hash"], json.dumps(client))
    await pipe.execute()
    return client


async def delete_client(client_id: str) -> bool:
    redis = await get_redis()
    raw = await redis.hget(CLIENTS_HASH, client_id)
    if not raw:
        return False
    client = json.loads(raw)
    pipe = redis.pipeline()
    pipe.hdel(CLIENTS_HASH, client_id)
    pipe.hdel(KEY_HASH_MAP, client["key_hash"])
    await pipe.execute()
    return True


async def seed_dev_clients() -> list[dict]:
    """Create default dev clients if none exist."""
    redis = await get_redis()
    existing = await redis.hlen(CLIENTS_HASH)
    if existing > 0:
        return []

    from app.models.schemas import ClientCreate, ClientTier
    results = []
    for name, tier in [("Dev Basic Client", ClientTier.basic), ("Dev Premium Client", ClientTier.premium)]:
        result = await create_client(ClientCreate(name=name, tier=tier))
        results.append(result)
        logger.info(f"Seeded dev client: {name} → key prefix {result['key_prefix']}")
    return results
