"""API key authentication helpers."""
import hashlib
import secrets
import json
import time
import logging
from fastapi import Request, HTTPException, status
from app.redis.client import get_redis

logger = logging.getLogger(__name__)

CLIENTS_KEY = "clients:registry"   # Redis Hash: client_id → JSON


def generate_api_key() -> str:
    """Generate a high-entropy API key."""
    return "rlk_" + secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the raw key – used as Redis lookup key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def authenticate_request(request: Request) -> dict:
    """
    Extract and validate X-API-Key header.
    Returns the client dict on success, raises HTTPException on failure.
    """
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_api_key", "message": "X-API-Key header is required"},
        )

    redis = await get_redis()
    key_hash = hash_api_key(raw_key)

    # Look up by hash
    client_json = await redis.hget("clients:by_key_hash", key_hash)
    if not client_json:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key", "message": "Invalid API key"},
        )

    client = json.loads(client_json)
    if not client.get("enabled", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "client_disabled", "message": "This API key has been disabled"},
        )

    return client
