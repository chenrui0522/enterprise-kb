"""Recall evaluation for the structure-aware chunking change.

Usage:
    uv run python scripts/eval_recall.py --ingest
    uv run python scripts/eval_recall.py --run
    uv run python scripts/eval_recall.py --ingest --run

Ingest reads every PDF under data/recall_eval, writes it into the configured
Milvus collection with the current (structure-aware) chunker, then --run scores
data/recall_eval/questions.jsonl against hybrid retrieval + rerank.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import create_tables_if_needed, get_session_factory  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.ingestion.pipeline import IngestionPipeline  # noqa: E402
from app.ingestion.storage import FileDocumentStorage  # noqa: E402
from app.models.entity import Document, DocumentVersion  # noqa: E402
from app.providers.factory import build_embedder, build_reranker  # noqa: E402
from app.retrieval.milvus_store import MilvusStore  # noqa: E402
from app.retrieval.service import SearchService  # noqa: E402

SAMPLES = ROOT / "data" / "recall_eval"
QUESTIONS_PATH = SAMPLES / "questions.jsonl"
RESULTS_PATH = SAMPLES / "results.json"

DOC_TYPE_HINTS = [
    ("员工手册", "policy"),
    ("提成", "policy"),
    ("案例", "generic"),
    ("企业介绍", "generic"),
]


def doc_type_for(filename: str) -> str:
    for needle, doc_type in DOC_TYPE_HINTS:
        if needle in filename:
            return doc_type
    return "generic"


async def ingest(tenant: str) -> None:
    settings = get_settings()
    await create_tables_if_needed()
    storage = FileDocumentStorage(settings.document_storage_dir)
    store = MilvusStore(settings)
    embedder = build_embedder(settings)
    pipeline = IngestionPipeline(store=store, embedder=embedder, storage=storage, settings=settings)
    session_factory = get_session_factory()

    files = sorted(SAMPLES.glob("*.pdf"))
    if not files:
        print("no sample PDFs found under", SAMPLES)
        return

    async with session_factory() as session:
        for path in files:
            existing = await session.execute(
                select(Document).where(Document.tenant_id == tenant, Document.filename == path.name)
            )
            document = existing.scalar_one_or_none()
            if document is not None and document.status == "ready":
                print(f"[skip] {path.name} already ready (doc={document.id})")
                continue
            if document is None:
                document = Document(
                    tenant_id=tenant,
                    title=path.stem,
                    filename=path.name,
                    status="pending",
                    stage="queued",
                )
                session.add(document)
                await session.flush()
            version = DocumentVersion(
                tenant_id=tenant,
                doc_id=document.id,
                status="pending",
                stage="queued",
                storage_key="",
                parse_mode="auto",
                doc_type=doc_type_for(path.name),
            )
            session.add(version)
            await session.flush()
            storage_key = storage.store(document.id, version.id, path.name, path.read_bytes())
            version.storage_key = storage_key
            await session.commit()
            print(f"[ingest] {path.name} doc={document.id} version={version.id} type={version.doc_type}")
            await pipeline.process_job(
                session,
                {
                    "doc_id": document.id,
                    "version_id": version.id,
                    "tenant_id": tenant,
                    "storage_key": storage_key,
                    "doc_type": version.doc_type,
                    "chunker_version": settings.chunker_version,
                },
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            await session.refresh(version)
            print(f"    -> status={version.status} chunks={version.chunk_count} chunker={version.chunker_version}")
            if version.status != "ready":
                print(f"    !! failed: {version.error_message}")


def _gold_title(question: dict) -> str:
    source = question.get("expected_source", "")
    first = source.split(" / ")[0].strip()
    return Path(first).stem if first else ""


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _keyword_present(keyword: str, text: str) -> bool:
    keyword = keyword or ""
    if not keyword:
        return False
    normalized_text = _normalized(text)
    if _normalized(keyword) in normalized_text:
        return True
    # PDF text extraction often inserts spaces around digits ("5 次", "20 日-30 日").
    tokens = re.findall(r"[0-9]+|[A-Za-z]+|[\u4e00-\u9fff]+", keyword)
    return bool(tokens) and all(token in normalized_text for token in tokens)


def _matches(question: dict, hit) -> bool:
    gold_title = _gold_title(question)
    if not gold_title:
        return False
    title_ok = gold_title in hit.title or hit.title in gold_title
    if not title_ok:
        return False
    page = int(question.get("source_page") or 0)
    if page and hit.page == page:
        return True
    keywords = [str(k) for k in question.get("expected_keywords") or []]
    return any(_keyword_present(keyword, hit.text) for keyword in keywords)


async def evaluate(tenant: str, top_k: int | None, limit: int | None, out_path: Path, clear_cache: bool = True) -> dict:
    settings = get_settings()
    store = MilvusStore(settings)
    store.ensure_collection()
    embedder = build_embedder(settings)
    reranker = build_reranker(settings)
    redis = get_redis()
    service = SearchService(settings, store, embedder, reranker, redis)

    # Drop cached retrieval results so the run reflects current chunks.
    if clear_cache:
        try:
            keys = [key async for key in redis.scan_iter(match="kb:retrieval:*")]
            if keys:
                await redis.delete(*keys)
        except Exception:
            pass

    questions = [
        json.loads(line)
        for line in QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit:
        questions = questions[:limit]

    results = []
    for question in questions:
        hits = await service.search(question["question"], tenant)
        if top_k:
            hits = hits[:top_k]
        rank = None
        for index, hit in enumerate(hits, start=1):
            if _matches(question, hit):
                rank = index
                break
        negative = question.get("doc_type") == "out-of-scope"
        results.append(
            {
                "id": question["id"],
                "question": question["question"],
                "doc_type": question["doc_type"],
                "category": question["category"],
                "difficulty": question.get("difficulty"),
                "negative": negative,
                "rank": rank,
                "hit": rank is not None,
                "returned": len(hits),
                "top_titles": [hit.title for hit in hits[:3]],
                "top_pages": [hit.page for hit in hits[:3]],
            }
        )
        marker = "NEG" if negative else ("HIT" if rank else "MISS")
        print(f"[{marker}] {question['id']} rank={rank} hits={len(hits)} :: {question['question'][:40]}")

    scored = [item for item in results if not item["negative"]]
    hits = [item for item in scored if item["hit"]]
    reciprocal = [1.0 / item["rank"] for item in hits if item["rank"]]
    summaries: dict[str, dict] = {}
    for key in ("category", "doc_type", "difficulty"):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for item in scored:
            buckets[str(item[key])].append(item)
        summaries[key] = {
            name: {
                "count": len(items),
                "hits": sum(1 for item in items if item["hit"]),
                "recall": round(sum(1 for item in items if item["hit"]) / len(items), 3) if items else 0.0,
            }
            for name, items in sorted(buckets.items())
        }

    overall = {
        "questions_total": len(results),
        "scored_questions": len(scored),
        "hits": len(hits),
        "recall_at_k": round(len(hits) / len(scored), 4) if scored else 0.0,
        "mrr": round(sum(reciprocal) / len(scored), 4) if scored else 0.0,
        "top_k": top_k or settings.retrieval_top_k,
        "collection": settings.milvus_collection,
        "chunker_version": settings.chunker_version,
        "negatives": [item for item in results if item["negative"]],
        "by_category": summaries["category"],
        "by_doc_type": summaries["doc_type"],
        "by_difficulty": summaries["difficulty"],
        "results": results,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    await close_redis()

    print()
    print("=" * 72)
    print(f"collection={overall['collection']}  scored={overall['scored_questions']}  "
          f"recall@{overall['top_k']}={overall['recall_at_k']:.3f}  MRR={overall['mrr']:.3f}")
    for key in ("doc_type", "difficulty"):
        print(f"{key}: " + ", ".join(
            f"{name}={value['hits']}/{value['count']}" for name, value in overall[f'by_{key}'].items()
        ))
    print(f"results written to {out_path}")
    return overall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest", action="store_true", help="ingest sample PDFs with the current chunker")
    parser.add_argument("--run", action="store_true", help="run the recall evaluation")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=str(RESULTS_PATH))
    parser.add_argument("--no-clear-cache", action="store_true", help="reuse cached retrieval hits")
    args = parser.parse_args()
    if not args.ingest and not args.run:
        parser.error("pass --ingest and/or --run")

    if args.ingest:
        asyncio.run(ingest(args.tenant))
    if args.run:
        asyncio.run(evaluate(args.tenant, args.top_k, args.limit, Path(args.out), clear_cache=not args.no_clear_cache))


if __name__ == "__main__":
    main()