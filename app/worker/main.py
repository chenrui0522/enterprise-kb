from __future__ import annotations

import asyncio
import json

from app.chat.memory.compress import run_compress_job
from app.chat.memory.queue import ack_compress_job, pop_compress_job, recover_stale_compress_jobs
from app.chat.title import run_title_polish_job
from app.core.config import get_settings
from app.core.db import create_tables_if_needed, get_session_factory
from app.core.logging import get_logger, logging_context, setup_logging
from app.core.redis import close_redis, get_redis
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.queue import ack_job, pop_job, recover_stale_jobs
from app.ingestion.storage import FileDocumentStorage
from app.providers.factory import build_embedder, build_llm
from app.retrieval.milvus_store import MilvusStore

logger = get_logger("worker")


async def run_once() -> None:
    settings = get_settings()
    redis = get_redis()
    await recover_stale_jobs(redis)
    await recover_stale_compress_jobs(redis)
    pipeline = IngestionPipeline(
        store=MilvusStore(settings),
        embedder=build_embedder(settings),
        storage=FileDocumentStorage(settings.document_storage_dir),
    )
    llm = build_llm(settings)
    logger.info("Worker started (ingestion + memory compress + title polish), waiting for jobs")
    while True:
        raw_memory = await pop_compress_job(redis)
        if raw_memory is not None:
            job = json.loads(raw_memory)
            conversation_id = str(job.get("conversation_id") or "unknown")
            job_type = str(job.get("type") or "memory_compress")
            with logging_context(
                job_id=conversation_id,
                request_id=conversation_id,
                conversation_id=conversation_id,
                tenant_id=job.get("tenant_id"),
            ):
                try:
                    async with get_session_factory()() as session:
                        if job_type == "title_polish":
                            logger.info("Processing title polish %s", conversation_id)
                            await run_title_polish_job(session, llm, job)
                        else:
                            logger.info("Processing memory compress %s", conversation_id)
                            await run_compress_job(session, redis, llm, job)
                except Exception:
                    logger.exception("%s failed for %s", job_type, conversation_id)
                finally:
                    await ack_compress_job(redis, raw_memory)
            continue

        raw_job = await pop_job(redis)
        if raw_job is None:
            await asyncio.sleep(0.2)
            continue
        job = json.loads(raw_job)
        job_id = str(job.get("job_id") or job.get("version_id") or job.get("doc_id") or "unknown")
        with logging_context(
            job_id=job_id,
            request_id=job_id,
            document_id=job.get("doc_id"),
            tenant_id=job.get("tenant_id"),
        ):
            logger.info("Processing ingestion job %s", job_id)
            async with get_session_factory()() as session:
                await pipeline.process_job(
                    session, job, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap
                )
            await ack_job(redis, raw_job)


async def main() -> None:
    setup_logging()
    await create_tables_if_needed()
    try:
        await run_once()
    finally:
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
