from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from app.core.logging import get_logger, log_event, timed_event
from app.providers.base import Embedder, LLMProvider, Reranker

logger = get_logger("providers")


class ObservedLLM(LLMProvider):
    def __init__(self, inner: LLMProvider, *, name: str = "llm") -> None:
        self._inner = inner
        self._name = name

    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        with timed_event(logger, "provider.call", provider=self._name, op="complete"):
            return await self._inner.complete(system=system, user=user, temperature=temperature)

    async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
        with timed_event(logger, "provider.call", provider=self._name, op="complete_json"):
            return await self._inner.complete_json(system=system, user=user, temperature=temperature)

    async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
        started = time.perf_counter()
        ok = True
        error: str | None = None
        try:
            async for delta in self._inner.stream(system=system, user=user, temperature=temperature):
                yield delta
        except Exception as exc:
            ok = False
            error = str(exc)[:200]
            raise
        finally:
            log_event(
                logger,
                "provider.call",
                level=logging.ERROR if not ok else logging.INFO,
                event="provider.call",
                provider=self._name,
                op="stream",
                duration_ms=int((time.perf_counter() - started) * 1000),
                ok=ok,
                error=error,
            )


class ObservedEmbedder(Embedder):
    def __init__(self, inner: Embedder, *, name: str = "embedder") -> None:
        self._inner = inner
        self._name = name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        with timed_event(
            logger, "provider.call", provider=self._name, op="embed", batch_size=len(texts)
        ):
            return await self._inner.embed(texts)


class ObservedReranker(Reranker):
    def __init__(self, inner: Reranker, *, name: str = "reranker") -> None:
        self._inner = inner
        self._name = name

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        with timed_event(
            logger,
            "provider.call",
            provider=self._name,
            op="rerank",
            doc_count=len(documents),
        ):
            return await self._inner.rerank(query, documents)
