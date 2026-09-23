from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.memory.tokens import estimate_tokens
from app.core.errors import NotFoundError
from app.models.entity import (
    AuditEvent,
    Conversation,
    ConversationSummary,
    FeedbackResponse,
    Message,
    MessageCitation,
)


async def create_conversation(
    session: AsyncSession,
    tenant_id: str,
    title: str | None = None,
    *,
    created_by: str = "local-user",
    title_source: str | None = None,
) -> Conversation:
    from app.chat.title import DEFAULT_TITLE, TITLE_SOURCE_AUTO, TITLE_SOURCE_DEFAULT, TITLE_SOURCE_USER

    resolved = (title or "").strip() or DEFAULT_TITLE
    if title_source:
        source = title_source
    elif resolved == DEFAULT_TITLE:
        source = TITLE_SOURCE_DEFAULT
    else:
        source = TITLE_SOURCE_AUTO
    if source not in (TITLE_SOURCE_DEFAULT, TITLE_SOURCE_AUTO, TITLE_SOURCE_USER):
        source = TITLE_SOURCE_DEFAULT
    conversation = Conversation(
        tenant_id=tenant_id,
        title=resolved,
        title_source=source,
        created_by=created_by,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def update_conversation_title(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str,
    title: str,
    *,
    created_by: str | None = None,
) -> Conversation:
    from app.chat.title import TITLE_SOURCE_USER
    from app.core.errors import AppError

    conversation = await get_conversation(
        session, tenant_id, conversation_id, created_by=created_by
    )
    cleaned = (title or "").strip()
    if not cleaned:
        raise AppError("标题不能为空", status_code=400)
    if len(cleaned) > 500:
        cleaned = cleaned[:500]
    conversation.title = cleaned
    conversation.title_source = TITLE_SOURCE_USER
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(
    session: AsyncSession,
    tenant_id: str,
    limit: int = 50,
    *,
    created_by: str | None = None,
) -> list[Conversation]:
    query = select(Conversation).where(Conversation.tenant_id == tenant_id)
    if created_by is not None:
        query = query.where(Conversation.created_by == created_by)
    result = await session.execute(query.order_by(Conversation.updated_at.desc()).limit(limit))
    return list(result.scalars())


async def get_conversation(
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str,
    *,
    created_by: str | None = None,
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        raise NotFoundError("会话不存在")
    if created_by is not None and conversation.created_by != created_by:
        raise NotFoundError("会话不存在")
    return conversation


async def list_messages(
    session: AsyncSession, tenant_id: str, conversation_id: str, *, created_by: str | None = None
) -> list[tuple[Message, list[MessageCitation]]]:
    await get_conversation(session, tenant_id, conversation_id, created_by=created_by)
    result = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.asc())
    )
    messages = list(result.scalars())
    if not messages:
        return []
    message_ids = [message.id for message in messages]
    citation_result = await session.execute(
        select(MessageCitation).where(MessageCitation.message_id.in_(message_ids))
    )
    citations_by_message: dict[str, list[MessageCitation]] = {}
    for citation in citation_result.scalars():
        citations_by_message.setdefault(citation.message_id, []).append(citation)
    return [(message, citations_by_message.get(message.id, [])) for message in messages]


async def get_latest_conversation_summary(
    session: AsyncSession, tenant_id: str, conversation_id: str, *, created_by: str | None = None
) -> ConversationSummary | None:
    await get_conversation(session, tenant_id, conversation_id, created_by=created_by)
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


async def save_user_message(
    session: AsyncSession,
    conversation_id: str,
    tenant_id: str,
    content: str,
    rewritten_query: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        role="user",
        content=content,
        rewritten_query=rewritten_query,
        compressed=False,
        token_count=estimate_tokens(content),
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def save_assistant_turn(
    session: AsyncSession,
    conversation_id: str,
    tenant_id: str,
    content: str,
    rewritten_query: str | None,
    citations: list[dict],
    meta: dict | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        role="assistant",
        content=content,
        rewritten_query=rewritten_query,
        meta=meta,
        compressed=False,
        token_count=estimate_tokens(content),
    )
    session.add(message)
    await session.flush()
    for citation in citations:
        session.add(
            MessageCitation(
                tenant_id=tenant_id,
                message_id=message.id,
                chunk_id=citation["chunk_id"],
                doc_id=citation["doc_id"],
                document_title=citation["document_title"],
                page=int(citation["page"]),
                section=citation.get("section"),
                image_id=citation.get("image_id") or None,
                score=citation.get("score"),
            )
        )
    await session.commit()
    await session.refresh(message)
    return message


async def write_audit(
    session: AsyncSession,
    tenant_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    actor: str = "local-user",
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )
    await session.commit()


async def save_feedback(
    session: AsyncSession,
    tenant_id: str,
    message_id: str,
    rating: str,
    comment: str | None,
) -> FeedbackResponse:
    message = await session.get(Message, message_id)
    if message is None or message.tenant_id != tenant_id:
        raise NotFoundError("消息不存在")
    feedback = FeedbackResponse(
        tenant_id=tenant_id, message_id=message_id, rating=rating, comment=comment
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return feedback
