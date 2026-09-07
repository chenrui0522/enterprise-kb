from __future__ import annotations

from typing import TypedDict


class ChatState(TypedDict):
    conversation_id: str
    tenant_id: str
    user_question: str
    # Plain dict messages: {"role": "user"|"assistant", "content": str}
    # Supplied from DB history at each turn (overwrite semantics; checkpointer-safe).
    history: list[dict]
    rewritten_query: str
    need_retrieval: bool
    hits: list[dict]
    citations: list[dict]
    answer: str
    refused: bool
    refusal_reason: str
