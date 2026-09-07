from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str: ...

    @abstractmethod
    async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict: ...

    @abstractmethod
    def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]: ...


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]: ...
