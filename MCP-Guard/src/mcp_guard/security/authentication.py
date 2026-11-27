"""Authentication utilities."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_api_key() -> str:
    """Generate a secure API key."""
    return f"mcp_guard_{secrets.token_urlsafe(32)}"


def hash_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_key(key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored hash."""
    return hmac.compare_digest(hash_key(key), stored_hash)
