from __future__ import annotations

from typing import NotRequired, TypedDict


class ChatState(TypedDict):
    conversation_id: str
    tenant_id: str
    user_question: str
    # Plain dict messages: {"role": "user"|"assistant", "content": str}
    # Uncompressed recent window from DB (overwrite semantics; checkpointer-safe).
    history: list[dict]
    # Latest rolling summary text (long-term memory); may be empty/absent.
    memory_summary: NotRequired[str]
    rewritten_query: str
    need_retrieval: bool
    # Optional metadata filter (doc_type / table_id / heading_path prefix ...);
    # applied as a Milvus expr on both retrieval routes, never as a ranked route.
    filters: dict
    # Live Principal scope for corpus visibility (never freeze auth cookies here).
    principal_scope: dict
    hits: list[dict]
    citations: list[dict]
    answer: str
    refused: bool
    refusal_reason: str
