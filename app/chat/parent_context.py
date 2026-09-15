"""Expand retrieved child chunks into their parent context for generation.

Retrieval stays precise (the child chunk is what matched); generation needs
enough context to answer well, so each hit is swapped for its parent chunk when
one exists. Parent rows live in PostgreSQL (`chunk_parents`), so this is a
single indexed lookup per distinct parent.

Budget rules (design D7):
* the same parent is only used once, even if three of its children matched;
* table/image chunks answer from their own text - they have no parent;
* the total context is capped by a token budget, split evenly across the
  distinct parents, and each oversized parent is truncated with an ellipsis.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.entity import ChunkParent
from app.retrieval.milvus_store import SELF_CONTAINED_KINDS

logger = get_logger("chat.parent_context")

#: CJK-heavy corpora run close to one token per 1.5-2 characters.
CHARS_PER_TOKEN = 2
MIN_PARENT_CHARS = 400


def char_budget(token_budget: int) -> int:
    return max(int(token_budget or 0), 1) * CHARS_PER_TOKEN


def truncate_text(text: str, budget: int, *, marker: str = "…") -> str:
    """Keep the head of an oversized text inside a character budget."""
    text = text or ""
    if budget <= 0 or len(text) <= budget:
        return text
    return text[: max(budget - len(marker), 1)].rstrip() + marker


async def expand_hits(
    session: AsyncSession,
    hits: list[dict],
    *,
    token_budget: int,
    max_parents: int,
) -> list[dict]:
    """Return the same hits with `context_text` filled from the parent chunk."""
    if not hits:
        return hits

    parent_ids: list[str] = []
    for hit in hits:
        parent_id = str(hit.get("parent_id") or "")
        if not parent_id:
            continue
        if (hit.get("chunk_kind") or "child") in SELF_CONTAINED_KINDS:
            continue
        if parent_id not in parent_ids:
            parent_ids.append(parent_id)

    budget = char_budget(token_budget)
    limit = max(int(max_parents or 1), 1)
    # Do not expand more parents than the budget can carry at a useful size.
    limit = min(limit, max(budget // MIN_PARENT_CHARS, 1))
    selected = parent_ids[:limit]
    texts: dict[str, str] = {}
    if selected:
        result = await session.execute(
            select(ChunkParent.id, ChunkParent.text).where(ChunkParent.id.in_(selected))
        )
        texts = {row[0]: row[1] for row in result.all()}

    per_parent = max(budget // max(len(selected), 1), 1) if selected else 0

    for hit in hits:
        parent_id = str(hit.get("parent_id") or "")
        text = texts.get(parent_id) if parent_id in selected else None
        if text:
            hit["context_text"] = truncate_text(text, per_parent)
            hit["context_source"] = "parent"
        else:
            hit["context_text"] = hit.get("text", "")
            hit["context_source"] = "child"
    if texts:
        logger.info(
            "Expanded %d hit(s) from %d parent chunk(s)", len(hits), len(texts)
        )
    return hits


def build_parent_expander(session_factory, settings):
    """Factory used by the API to inject expansion into the chat graph."""

    async def expander(hits: list[dict]) -> list[dict]:
        async with session_factory() as session:
            return await expand_hits(
                session,
                hits,
                token_budget=settings.parent_token_budget,
                max_parents=settings.max_parents_per_answer,
            )

    return expander