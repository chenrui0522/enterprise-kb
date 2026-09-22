from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings
from app.core.db import create_tables_if_needed, get_session_factory
from app.core.logging import get_logger, logging_context, setup_logging
from app.core.redis import close_redis, get_redis
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.queue import ack_job, pop_job, recover_stale_jobs
from app.ingestion.storage import FileDocumentStorage
from app.providers.factory import build_embedder
from app.retrieval.milvus_store import MilvusStore

logger = get_logger("worker")


async def run_once() -> None:
    settings = get_settings()
    redis = get_redis()
    await recover_stale_jobs(redis)
    pipeline = IngestionPipeline(
        store=MilvusStore(settings),
        embedder=build_embedder(settings),
        storage=FileDocumentStorage(settings.document_storage_dir),
    )
    logger.info("Ingestion worker started, waiting for jobs")
    while True:
        raw_job = await pop_job(redis)
        if raw_job is None:
            await asyncio.sleep(1.0)
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
