from __future__ import annotations

import json
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger, log_event

logger = get_logger("chat.memory.queue")


def make_compress_job(
    *,
    conversation_id: str,
    tenant_id: str,
    window_tokens: int,
    enqueued_at_ms: int | None = None,
) -> str:
    return json.dumps(
        {
            "type": "memory_compress",
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "window_tokens": window_tokens,
            "enqueued_at_ms": enqueued_at_ms or int(time.time() * 1000),
        },
        ensure_ascii=False,
    )


async def enqueue_compress(redis: Redis, job: str) -> None:
    settings = get_settings()
    await redis.rpush(settings.memory_queue_key, job)


async def pop_compress_job(redis: Redis) -> str | None:
    """Non-blocking pop so the worker can also service ingestion."""
    settings = get_settings()
    try:
        raw = await redis.lpop(settings.memory_queue_key)
        if raw is None:
            return None
        await redis.rpush(settings.memory_queue_processing_key, raw)
        return raw
    except RedisError:
        logger.warning("Redis briefly unavailable for memory queue", exc_info=True)
        return None


async def ack_compress_job(redis: Redis, job: str) -> None:
    settings = get_settings()
    await redis.lrem(settings.memory_queue_processing_key, 1, job)


async def recover_stale_compress_jobs(redis: Redis) -> None:
    settings = get_settings()
    stale = await redis.lrange(settings.memory_queue_processing_key, 0, -1)
    if not stale:
        return
    await redis.rpush(settings.memory_queue_key, *stale)
    await redis.delete(settings.memory_queue_processing_key)
    logger.warning("Recovered %d stale memory compress job(s)", len(stale))


async def acquire_compress_lock(redis: Redis, conversation_id: str, ttl_seconds: int = 120) -> bool:
    settings = get_settings()
    key = f"{settings.memory_compress_lock_prefix}{conversation_id}"
    return bool(await redis.set(key, "1", nx=True, ex=ttl_seconds))


async def release_compress_lock(redis: Redis, conversation_id: str) -> None:
    settings = get_settings()
    key = f"{settings.memory_compress_lock_prefix}{conversation_id}"
    await redis.delete(key)


async def maybe_enqueue_compress(
    redis: Redis,
    *,
    conversation_id: str,
    tenant_id: str,
    window_tokens: int,
) -> bool:
    """Enqueue when uncompressed window exceeds budget. Returns True if enqueued."""
    settings = get_settings()
    budget = settings.memory_token_budget
    over = window_tokens > budget
    log_event(
        logger,
        "memory budget check",
        event="memory.budget_check",
        conversation_id=conversation_id,
        window_tokens=window_tokens,
        budget=budget,
        over_budget=over,
    )
    if not over:
        return False
    job = make_compress_job(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        window_tokens=window_tokens,
    )
    await enqueue_compress(redis, job)
    log_event(
        logger,
        "memory compress enqueued",
        event="memory.compress_enqueued",
        conversation_id=conversation_id,
        window_tokens=window_tokens,
    )
    return True
