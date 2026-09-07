from __future__ import annotations

import time

from redis.asyncio import Redis

from app.core.config import get_settings


async def check_rate_limit(redis: Redis, key: str) -> tuple[bool, int]:
    """Return (allowed, remaining). Fixed window per minute keyed by `key`."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return True, settings.rate_limit_per_minute
    window = 60
    now = int(time.time())
    bucket = f"kb:rl:{key}:{now // window}"
    try:
        count = await redis.incr(bucket)
        if count == 1:
            await redis.expire(bucket, window + 1)
        allowed = count <= settings.rate_limit_per_minute
        remaining = max(settings.rate_limit_per_minute - count, 0)
        return allowed, remaining
    except Exception:
        # Degrade open when Redis is unavailable; chat must not hard-fail.
        return True, settings.rate_limit_per_minute
