from __future__ import annotations

import asyncio
import hashlib
import json

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import Embedder, Reranker
from app.retrieval.chunk import SearchHit
from app.retrieval.milvus_store import MilvusStore

logger = get_logger("retrieval.service")


class SearchService:
    """Orchestrates hybrid search + rerank + Redis caching for one tenant scope."""

    def __init__(
        self,
        settings: Settings,
        store: MilvusStore,
        embedder: Embedder,
        reranker: Reranker,
        redis: Redis,
    ) -> None:
        self._settings = settings
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._redis = redis
        self._rerank_semaphore = asyncio.Semaphore(settings.rerank_max_concurrency)

    async def search(self, query: str, tenant_id: str) -> list[SearchHit]:
        top_n = self._settings.retrieval_top_n
        top_k = self._settings.retrieval_top_k
        cache_key = self._cache_key(query, tenant_id, top_n, top_k)
        cached = await self._redis.get(cache_key)
        if cached:
            try:
                return [SearchHit.model_validate(item) for item in json.loads(cached)]
            except Exception:
                logger.warning("Ignored corrupted retrieval cache entry")

        query_vector = (await self._embedder.embed([query]))[0]
        candidates = self._store.hybrid_search(query, query_vector, tenant_id, top_n)
        hits = await self._rank(query, candidates, top_k)
        try:
            payload = json.dumps([hit.model_dump() for hit in hits], ensure_ascii=False)
            await self._redis.set(cache_key, payload, ex=self._settings.retrieval_cache_ttl)
        except Exception:
            logger.warning("Failed to write retrieval cache")
        return hits

    async def _rank(self, query: str, candidates: list[dict], top_k: int) -> list[SearchHit]:
        if not candidates:
            return []
        if len(candidates) <= top_k:
            return [_to_hit(candidate) for candidate in candidates[:top_k]]
        async with self._rerank_semaphore:
            scores = await self._reranker.rerank(query, [candidate["text"] for candidate in candidates])
        ranked = sorted(
            ((_to_hit(candidate), score) for candidate, score in zip(candidates, scores, strict=False)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        min_score = getattr(self._settings, "rerank_min_score", 0.0)
        hits = [hit for hit, score in ranked if score >= min_score][:top_k]
        return hits

    def _cache_key(self, query: str, tenant_id: str, top_n: int, top_k: int) -> str:
        digest = hashlib.sha1(f"{tenant_id}|{query}|{top_n}|{top_k}".encode("utf-8")).hexdigest()
        return f"kb:retrieval:{digest}"


def _to_hit(candidate: dict) -> SearchHit:
    return SearchHit(
        chunk_id=candidate["id"],
        doc_id=candidate.get("doc_id", ""),
        version_id=candidate.get("version_id", ""),
        title=candidate.get("title", ""),
        page=int(candidate.get("page") or 0),
        section=candidate.get("section", "") or "",
        text=candidate.get("text", ""),
        score=float(candidate.get("score") or 0.0),
        chunk_type=candidate.get("chunk_type", "") or "text",
        heading_path=candidate.get("heading_path", "") or "",
        clause_no=candidate.get("clause_no", "") or "",
        step_no=candidate.get("step_no", "") or "",
        faq_id=candidate.get("faq_id", "") or "",
        table_id=candidate.get("table_id", "") or "",
        row_start=int(candidate.get("row_start") or 0),
        row_end=int(candidate.get("row_end") or 0),
        parent_id=candidate.get("parent_id", "") or "",
        chunker_version=candidate.get("chunker_version", "") or "",
    )