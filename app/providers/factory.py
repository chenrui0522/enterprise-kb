from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.base import Embedder, LLMProvider, Reranker
from app.providers.deepseek import DeepSeekProvider
from app.providers.xinference import XinferenceEmbedder, XinferenceReranker


def build_llm(settings: Settings | None = None) -> LLMProvider:
    return DeepSeekProvider(settings or get_settings())


def build_embedder(settings: Settings | None = None) -> Embedder:
    return XinferenceEmbedder(settings or get_settings())


def build_reranker(settings: Settings | None = None) -> Reranker:
    return XinferenceReranker(settings or get_settings())
