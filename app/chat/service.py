from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.entity import (
    AuditEvent,
    Conversation,
    FeedbackResponse,
    Message,
    MessageCitation,
)


async def create_conversation(session: AsyncSession, tenant_id: str, title: str | None = None) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id, title=title or "新对话")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession, tenant_id: str, limit: int = 50) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def get_conversation(
    session: AsyncSession, tenant_id: str, conversation_id: str
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        raise NotFoundError("会话不存在")
    return conversation


async def list_messages(
    session: AsyncSession, tenant_id: str, conversation_id: str
) -> list[tuple[Message, list[MessageCitation]]]:
    await get_conversation(session, tenant_id, conversation_id)
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
