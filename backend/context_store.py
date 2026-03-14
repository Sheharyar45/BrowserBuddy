import json
import os
from functools import lru_cache
from typing import Any

import redis


KEY_PREFIX = "browserbuddy:context:"


@lru_cache(maxsize=1)
def _redis_client() -> redis.Redis:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Redis is not reachable. Start Redis and/or set REDIS_URL. "
            f"Current REDIS_URL={redis_url}"
        ) from exc
    return client


def _key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}"


def save_context(session_id: str, context: dict[str, Any]) -> None:
    ttl_raw = os.environ.get("CONTEXT_TTL_SECONDS", "3600")
    try:
        ttl_seconds = int(ttl_raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid CONTEXT_TTL_SECONDS: {ttl_raw}") from exc

    payload = json.dumps(context)
    client = _redis_client()
    if ttl_seconds > 0:
        client.setex(_key(session_id), ttl_seconds, payload)
    else:
        client.set(_key(session_id), payload)


def get_context(session_id: str) -> dict[str, Any] | None:
    client = _redis_client()
    raw = client.get(_key(session_id))
    if raw is None:
        return None
    return json.loads(raw)
