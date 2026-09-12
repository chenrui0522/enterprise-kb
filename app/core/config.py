from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables prefixed with KB_."""

    model_config = SettingsConfigDict(
        env_prefix="KB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "dev"
    debug: bool = True
    auto_create_tables: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://kb:kb@localhost:5432/kb"
    db_pool_size: int = 10
    db_max_overflow: int = 40

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    # DeepSeek generation model
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_temperature: float = 0.2

    # Local embedding model (Xinference /v1 OpenAI-compatible)
    embedder_base_url: str = "http://localhost:9997/v1"
    embedder_api_key: str = "xinference-local"
    embedder_model: str = "bge-m3"

    # Local reranker (Xinference /v1/rerank)
    reranker_base_url: str = "http://localhost:9997/v1"
    reranker_model: str = "bge-reranker-v2-m3"
    rerank_max_concurrency: int = 10

    # Milvus
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "kb_chunks"
    milvus_vector_dim: int = 1024

    # Retrieval tuning (initial defaults; tune on the real corpus)
    retrieval_top_n: int = 20
    retrieval_top_k: int = 3
    rerank_min_score: float = 0.0
    retrieval_cache_ttl: int = 300

    # Ingestion chunking
    chunk_size: int = 800
    chunk_overlap: int = 80
    chunker_version: str = "structure-v1"
    embed_batch_size: int = 32
    history_turns: int = 5

    # Document storage & queue
    document_storage_dir: str = "./data/documents"
    queue_key: str = "kb:ingestion:jobs"
    queue_processing_key: str = "kb:ingestion:processing"

    # MinerU OCR service (optional). When mineru_url is set, image uploads and
    # scanned PDFs are parsed by a remote mineru-api service; complex layout
    # manuals can force OCR at upload time via parse_mode="ocr".
    mineru_url: str = ""
    mineru_api_key: str = ""
    mineru_timeout_seconds: int = 3600
    mineru_poll_interval: float = 3.0
    mineru_lang: str = "ch"
    mineru_backend: str = "pipeline"
    mineru_table_enable: bool = True
    mineru_formula_enable: bool = False

    @property
    def mineru_enabled(self) -> bool:
        return bool(self.mineru_url.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def langgraph_pg_url(self) -> str:
        """DSN for langgraph-checkpoint-postgres (psycopg driver, not asyncpg)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
