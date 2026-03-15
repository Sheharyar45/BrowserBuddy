"""
Context store for BrowserBuddy.

Tries Redis first; falls back to an in-memory dict so the backend
works out of the box without any external services.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger("browserbuddy.context_store")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
KEY_PREFIX = "browserbuddy:context:"

_redis_client_instance: Any = None  # Will be redis.Redis or sentinel
_redis_available: bool | None = None  # None = not checked yet
_memory_store: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Redis helper (lazy init, fails gracefully)
# ---------------------------------------------------------------------------


def _get_redis() -> Any | None:
    """Return a connected Redis client, or None if Redis is unavailable."""
    global _redis_client_instance, _redis_available

    if _redis_available is not None:
        return _redis_client_instance if _redis_available else None

    try:
        import redis  # type: ignore[import-untyped]

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _redis_client_instance = client
        _redis_available = True
        logger.info("Connected to Redis at %s", redis_url)
        return client
    except Exception as exc:
        _redis_client_instance = None
        _redis_available = False
        logger.warning(
            "Redis not available — using in-memory store. (%s)", exc
        )
        return None


def _key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_context(session_id: str, context: dict[str, Any]) -> None:
    payload = json.dumps(context)
    client = _get_redis()

    if client is not None:
        ttl_raw = os.environ.get("CONTEXT_TTL_SECONDS", "3600")
        try:
            ttl_seconds = int(ttl_raw)
        except ValueError:
            ttl_seconds = 3600

        if ttl_seconds > 0:
            client.setex(_key(session_id), ttl_seconds, payload)
        else:
            client.set(_key(session_id), payload)
    else:
        _memory_store[session_id] = payload


def get_context(session_id: str) -> dict[str, Any] | None:
    client = _get_redis()

    if client is not None:
        raw = client.get(_key(session_id))
    else:
        raw = _memory_store.get(session_id)

    if raw is None:
        return None
    return json.loads(raw)
