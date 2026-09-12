from __future__ import annotations

import json

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("ingestion.queue")


def make_job(
    doc_id: str,
    version_id: str,
    tenant_id: str,
    storage_key: str,
    *,
    doc_type: str | None = None,
    chunker_version: str | None = None,
    reindex: bool = False,
) -> str:
    payload = {
        "doc_id": doc_id,
        "version_id": version_id,
        "tenant_id": tenant_id,
        "storage_key": storage_key,
    }
    if doc_type:
        payload["doc_type"] = doc_type
    if chunker_version:
        payload["chunker_version"] = chunker_version
    if reindex:
        payload["reindex"] = True
    return json.dumps(payload, ensure_ascii=False)


async def enqueue_job(redis: Redis, job: str) -> None:
    settings = get_settings()
    await redis.rpush(settings.queue_key, job)


async def pop_job(redis: Redis) -> str | None:
    settings = get_settings()
    try:
        return await redis.blmove(
            settings.queue_key, settings.queue_processing_key, timeout=5, src="LEFT", dest="RIGHT"
        )
    except RedisError:
        logger.warning("Redis 短暂不可用，稍后重试", exc_info=True)
        return None


async def ack_job(redis: Redis, job: str) -> None:
    settings = get_settings()
    await redis.lrem(settings.queue_processing_key, 1, job)


async def recover_stale_jobs(redis: Redis) -> None:
    """Return jobs stranded in the processing list back to the queue on startup."""
    settings = get_settings()
    stale = await redis.lrange(settings.queue_processing_key, 0, -1)
    if not stale:
        return
    if stale:
        await redis.rpush(settings.queue_key, *stale)
        await redis.delete(settings.queue_processing_key)
        logger.warning("Recovered %d stale ingestion job(s) from a previous worker run", len(stale))
