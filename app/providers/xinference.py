from __future__ import annotations

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.providers.base import Embedder, Reranker


class XinferenceEmbedder(Embedder):
    """bge-m3 embeddings served by a local Xinference instance (OpenAI-compatible)."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.embedder_api_key,
            base_url=settings.embedder_base_url,
            timeout=120.0,
            max_retries=2,
        )
        self._model = settings.embedder_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._model, input=texts)
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]


class XinferenceReranker(Reranker):
    """bge-reranker-v2-m3 via Xinference /v1/rerank."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.reranker_base_url
        self._model = settings.reranker_model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        try:
            resp = await self._client.post(
                f"{self._base_url.rstrip('/')}/rerank",
                json={"model": self._model, "query": query, "documents": documents},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:  # pragma: no cover - depends on upstream
            raise UpstreamError(f"重排服务调用失败：{exc}") from exc
        payload = resp.json()
        results = payload.get("results", [])
        scores = [0.0] * len(documents)
        for item in results:
            scores[item["index"]] = item.get("relevance_score", 0.0)
        return scores

    async def close(self) -> None:
        await self._client.aclose()
