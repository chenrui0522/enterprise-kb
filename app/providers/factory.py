from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.base import Embedder, LLMProvider, Reranker
from app.providers.deepseek import DeepSeekProvider
from app.providers.observability import ObservedEmbedder, ObservedLLM, ObservedReranker
from app.providers.xinference import XinferenceEmbedder, XinferenceReranker


def build_llm(settings: Settings | None = None) -> LLMProvider:
    return ObservedLLM(DeepSeekProvider(settings or get_settings()), name="llm")


def build_embedder(settings: Settings | None = None) -> Embedder:
    return ObservedEmbedder(XinferenceEmbedder(settings or get_settings()), name="embedder")


def build_reranker(settings: Settings | None = None) -> Reranker:
    return ObservedReranker(XinferenceReranker(settings or get_settings()), name="reranker")
