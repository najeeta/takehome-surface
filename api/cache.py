import hashlib
import json
import os
import struct

import redis

from retrieval import embed

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _cache_key(question: str) -> str:
    """Build a cache key from the sha256 of the question's embedding bytes."""
    embedding = embed(question)
    embedding_bytes = struct.pack(f"{len(embedding)}f", *embedding)
    digest = hashlib.sha256(embedding_bytes).hexdigest()
    return f"cache:query:{digest}"


def cache_get(question: str) -> dict | None:
    """Return the cached response for *question*, or None on a miss."""
    key = _cache_key(question)
    raw = _redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def cache_set(question: str, response: dict) -> None:
    """Store *response* in the cache with the configured TTL."""
    key = _cache_key(question)
    _redis.set(key, json.dumps(response), ex=CACHE_TTL)
