"""Full corpus reindex entry point.

Usage:
    uv run python -m app.reindex --dry-run
    uv run python -m app.reindex
    uv run python -m app.reindex --wait --timeout 3600
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_tables_if_needed, get_session_factory
from app.core.logging import setup_logging
from app.core.redis import close_redis, get_redis
from app.ingestion.doc_types import normalize_doc_type
from app.ingestion.queue import enqueue_job, make_job
from app.ingestion.storage import FileDocumentStorage
from app.models.entity import Document, DocumentVersion

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass
class ReindexItem:
    doc_id: str
    version_id: str
    title: str
    filename: str
    doc_type: str
    storage_key: str
    exists: bool
    reason: str = ""


async def collect_versions(session: AsyncSession, storage: FileDocumentStorage) -> list[ReindexItem]:
    """List every stored document version and whether its original still exists."""
    result = await session.execute(
        select(DocumentVersion, Document)
        .join(Document, Document.id == DocumentVersion.doc_id)
        .order_by(Document.created_at, DocumentVersion.created_at)
    )
    items: list[ReindexItem] = []
    for version, document in result.all():
        exists = False
        reason = ""
        if not version.storage_key:
            reason = "missing storage_key"
        else:
            try:
                path = storage.resolve(version.storage_key)
                exists = path.is_file()
                if not exists:
                    reason = "original file not found"
            except Exception as exc:  # pragma: no cover - defensive
                reason = f"invalid storage key: {exc}"
        items.append(
            ReindexItem(
                doc_id=document.id,
                version_id=version.id,
                title=document.title,
                filename=document.filename,
                doc_type=version.doc_type or "auto",
                storage_key=version.storage_key,
                exists=exists,
                reason=reason,
            )
        )
    return items


async def run(
    *,
    dry_run: bool = False,
    wait: bool = False,
    timeout: float = 3600.0,
    doc_type_override: str | None = None,
) -> dict:
    settings = get_settings()
    await create_tables_if_needed()
    storage = FileDocumentStorage(settings.document_storage_dir)
    session_factory = get_session_factory()

    async with session_factory() as session:
        items = await collect_versions(session, storage)
        if dry_run:
            return {
                "dry_run": True,
                "items": items,
                "queued": 0,
                "skipped": sum(1 for item in items if not item.exists),
            }

        queued: list[ReindexItem] = []
        skipped: list[ReindexItem] = []
        redis = get_redis()
        try:
            for item in items:
                if not item.exists:
                    skipped.append(item)
                    continue
                version = await session.get(DocumentVersion, item.version_id)
                document = await session.get(Document, item.doc_id)
                if version is None or document is None:
                    skipped.append(item)
                    continue
                resolved = normalize_doc_type(doc_type_override or item.doc_type)
                version.doc_type = resolved
                version.status = "pending"
                version.stage = "queued"
                version.error_message = None
                version.attempt += 1
                document.status = "pending"
                document.stage = "queued"
                document.error_message = None
                await session.commit()
                await enqueue_job(
                    redis,
                    make_job(
                        item.doc_id,
                        item.version_id,
                        version.tenant_id,
                        item.storage_key,
                        doc_type=resolved if resolved != "auto" else None,
                        chunker_version=settings.chunker_version,
                        reindex=True,
                    ),
                )
                queued.append(item)
        finally:
            await close_redis()

        summary = {
            "dry_run": False,
            "queued": len(queued),
            "skipped": len(skipped),
            "skipped_items": skipped,
            "chunker_version": settings.chunker_version,
        }
        if wait:
            summary["results"] = await _wait_for_completion(
                session_factory, [item.version_id for item in queued], timeout
            )
        return summary


async def _wait_for_completion(session_factory, version_ids: list[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    pending = set(version_ids)
    results: dict[str, dict] = {}
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        async with session_factory() as session:
            for version_id in list(pending):
                version = await session.get(DocumentVersion, version_id)
                if version is None:
                    pending.discard(version_id)
                    continue
                if version.status in {"ready", "failed"}:
                    results[version_id] = {
                        "status": version.status,
                        "chunks": version.chunk_count,
                        "chunker_version": version.chunker_version or "",
                        "error": version.error_message or "",
                    }
                    pending.discard(version_id)
    for version_id in pending:
        results[version_id] = {
            "status": "timeout",
            "chunks": 0,
            "chunker_version": "",
            "error": "reindex wait timed out",
        }
    return results


def format_summary(summary: dict) -> str:
    lines: list[str] = []
    if summary.get("dry_run"):
        lines.append(f"DRY-RUN documents={len(summary['items'])} skipped={summary['skipped']}")
        for item in summary["items"]:
            mark = "OK" if item.exists else "SKIP"
            lines.append(
                f"  [{mark}] {item.doc_id}/{item.version_id} type={item.doc_type} "
                f"file={item.filename} {item.reason}".rstrip()
            )
        return "\n".join(lines)
    lines.append(
        f"queued={summary['queued']} skipped={summary['skipped']} "
        f"chunker_version={summary.get('chunker_version', '')}"
    )
    for item in summary.get("skipped_items", []):
        lines.append(f"  [SKIP] {item.doc_id}/{item.version_id} file={item.filename} {item.reason}")
    for version_id, result in (summary.get("results") or {}).items():
        lines.append(
            f"  [{result['status']}] {version_id} chunks={result['chunks']} "
            f"chunker={result['chunker_version']} {result['error']}".rstrip()
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reindex every stored document version into the current Milvus collection."
    )
    parser.add_argument("--dry-run", action="store_true", help="only list versions and storage state")
    parser.add_argument("--wait", action="store_true", help="poll until queued reindex jobs finish")
    parser.add_argument("--timeout", type=float, default=3600.0, help="wait timeout in seconds")
    parser.add_argument(
        "--doc-type",
        default=None,
        choices=["faq", "policy", "sop", "table", "generic", "auto"],
        help="override doc_type for every version",
    )
    return parser


async def main() -> None:
    setup_logging()
    args = build_parser().parse_args()
    summary = await run(
        dry_run=args.dry_run,
        wait=args.wait,
        timeout=args.timeout,
        doc_type_override=args.doc_type,
    )
    print(format_summary(summary))


if __name__ == "__main__":
    asyncio.run(main())