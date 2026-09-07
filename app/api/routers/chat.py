from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import sse_event
from app.chat.graph import ChatGraph
from app.chat.service import (
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    save_assistant_turn,
    save_feedback,
    save_user_message,
    write_audit,
)
from app.core.db import get_db_session, get_session_factory
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.ratelimit import check_rate_limit
from app.core.redis import get_redis
from app.core.tenant import tenant_dependency
from app.models.entity import Message
from app.schemas.chat import (
    ChatRequest,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    FeedbackIn,
    MessageOut,
)

logger = get_logger("api.chat")
router = APIRouter(tags=["chat"])


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation_endpoint(
    payload: ConversationCreate | None = None,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> ConversationOut:
    conversation = await create_conversation(
        session, tenant_id, title=payload.title if payload else None
    )
    return ConversationOut.model_validate(conversation)


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations_endpoint(
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> list[ConversationOut]:
    conversations = await list_conversations(session, tenant_id)
    return [ConversationOut.model_validate(item) for item in conversations]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def messages_endpoint(
    conversation_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> list[MessageOut]:
    rows = await list_messages(session, tenant_id, conversation_id)
    output: list[MessageOut] = []
    for message, citations in rows:
        output.append(
            MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                rewritten_query=message.rewritten_query,
                citations=[
                    CitationOut(
                        chunk_id=item.chunk_id,
                        doc_id=item.doc_id,
                        document_title=item.document_title,
                        page=item.page,
                        section=item.section,
                    )
                    for item in citations
                ],
                created_at=message.created_at,
            )
        )
    return output


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    tenant_id: str = Depends(tenant_dependency),
) -> StreamingResponse:
    redis = get_redis()
    client_key = request.client.host if request.client else "unknown"
    allowed, _ = await check_rate_limit(redis, f"{tenant_id}:{client_key}")
    if not allowed:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    graph: ChatGraph = request.app.state.chat_graph
    return StreamingResponse(
        _chat_event_stream(graph, payload, tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _chat_event_stream(graph: ChatGraph, payload: ChatRequest, tenant_id: str) -> AsyncIterator[str]:
    session_factory = get_session_factory()
    try:
        # Phase 1: short-lived session for conversation + user message.
        async with session_factory() as session:
            if payload.conversation_id:
                conversation = await get_conversation(session, tenant_id, payload.conversation_id)
            else:
                conversation = await create_conversation(
                    session, tenant_id, title=payload.message[:30]
                )
            conversation_id = conversation.id
            yield sse_event({"event": "message_start", "data": {"conversation_id": conversation_id}})

            rows = await list_messages(session, tenant_id, conversation_id)
            history = [{"role": item.role, "content": item.content} for item, _ in rows]
            user_message = await save_user_message(
                session, conversation_id, tenant_id, payload.message
            )

        config = {"configurable": {"thread_id": conversation_id}}
        input_state = {
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "user_question": payload.message,
            "history": history + [{"role": "user", "content": payload.message}],
        }

        error_detail: str | None = None
        last_state: dict | None = None
        try:
            async for event in graph.graph.astream(
                input_state, config=config, stream_mode=["custom", "values"]
            ):
                if not isinstance(event, tuple) or len(event) != 2:
                    continue
                mode, event_payload = event
                if mode == "custom":
                    event_type = event_payload.get("type")
                    if event_type == "token":
                        yield sse_event({"event": "token", "data": event_payload.get("content", "")})
                    elif event_type == "error":
                        error_detail = event_payload.get("detail")
                        yield sse_event({"event": "error", "data": error_detail})
                elif mode == "values":
                    last_state = event_payload
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Chat graph failed")
            error_detail = str(exc)
            yield sse_event({"event": "error", "data": error_detail})

        values = last_state or {}
        answer = values.get("answer") or "（未生成回答）"
        citations = values.get("citations") or []
        rewritten_query = values.get("rewritten_query")

        # Phase 2: short-lived session to persist the assistant turn.
        async with session_factory() as session:
            if rewritten_query:
                user_row = await session.get(Message, user_message.id)
                if user_row is not None:
                    user_row.rewritten_query = rewritten_query
                    await session.commit()
            assistant_message = await save_assistant_turn(
                session,
                conversation_id,
                tenant_id,
                answer,
                rewritten_query=rewritten_query,
                citations=citations,
                meta={"refused": bool(values.get("refused"))},
            )
            await write_audit(
                session,
                tenant_id,
                action="chat.completion",
                resource_type="conversation",
                resource_id=conversation_id,
                detail={"user_message_id": user_message.id, "assistant_message_id": assistant_message.id},
            )
        yield sse_event(
            {
                "event": "done",
                "data": {
                    "conversation_id": conversation_id,
                    "message_id": assistant_message.id,
                    "answer": answer,
                    "citations": citations,
                    "error": error_detail,
                },
            }
        )
    except AppError as exc:
        yield sse_event({"event": "error", "data": exc.message})


@router.post("/feedback", status_code=201)
async def submit_feedback(
    payload: FeedbackIn,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_dependency),
) -> dict:
    feedback = await save_feedback(session, tenant_id, payload.message_id, payload.rating, payload.comment)
    return {"id": feedback.id, "message_id": feedback.message_id, "rating": feedback.rating}
