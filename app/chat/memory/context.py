from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.memory.tokens import estimate_tokens
from app.models.entity import ConversationSummary, Message


async def get_latest_summary(
    session: AsyncSession, tenant_id: str, conversation_id: str
) -> ConversationSummary | None:
    result = await session.execute(
        select(ConversationSummary)
        .where(
            ConversationSummary.tenant_id == tenant_id,
            ConversationSummary.conversation_id == conversation_id,
        )
        .order_by(ConversationSummary.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_uncompressed_messages(
    session: AsyncSession, tenant_id: str, conversation_id: str
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.compressed.is_(False),
        )
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars())


async def window_token_total(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        tokens = message.token_count or estimate_tokens(message.content)
        total += tokens
    return total


async def build_chat_context(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str,
    *,
    history_turns: int,
) -> dict:
    """Three-layer context: summary + uncompressed recent messages.

    Returns:
      memory_summary: str | None
      history: list[{role, content}]  (uncompressed only; caller appends current user msg)
      window_tokens: int
    """
    summary = await get_latest_summary(session, tenant_id, conversation_id)
    uncompressed = await list_uncompressed_messages(session, tenant_id, conversation_id)
    # Keep at most history_turns rounds in the prompt window (still all uncompressed
    # messages count toward the budget for enqueue decisions).
    keep = history_turns * 2
    recent = uncompressed[-keep:] if keep < len(uncompressed) else uncompressed
    history = [{"role": item.role, "content": item.content} for item in recent]
    return {
        "memory_summary": summary.content if summary else None,
        "history": history,
        "window_tokens": await window_token_total(uncompressed),
        "summary": summary,
        "uncompressed": uncompressed,
    }
