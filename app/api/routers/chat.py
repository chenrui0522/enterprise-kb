from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.events import sse_event
from app.chat.graph import ChatGraph
from app.chat.memory.compress import maybe_enqueue_compress_for_conversation
from app.chat.memory.context import build_chat_context
from app.chat.service import (
    create_conversation,
    get_conversation,
    get_latest_conversation_summary,
    list_conversations,
    list_messages,
    save_assistant_turn,
    save_feedback,
    save_user_message,
    update_conversation_title,
    write_audit,
)
from app.chat.title import (
    TITLE_SOURCE_AUTO,
    TITLE_SOURCE_USER,
    apply_rule_title_if_default,
    derive_rule_title,
    maybe_enqueue_title_polish,
)
from app.chat.tools.attachments import load_attachment, save_chat_xlsx
from app.chat.tools.registry import WEAK_CLARIFY_COPY, list_tools_for_principal
from app.chat.tools.router import (
    route_turn,
    user_affirms_staffing,
    user_declines_staffing,
)
from app.chat.tools.staffing_orchestrator import (
    apply_tool_action,
    clear_tool_state,
    handle_staffing_message,
    set_tool_state,
    update_staffing_state,
)
from app.core.config import get_settings
from app.core.db import get_db_session, get_session_factory
from app.core.errors import AppError
from app.core.logging import bind_context, get_log_context, get_logger, log_event, logging_context, preview_text
from app.core.ratelimit import check_rate_limit
from app.core.redis import get_redis
from app.identity.constants import PERM_CHAT_USE
from app.identity.deps import require_permission, tenant_from_principal
from app.identity.principal import Principal
from app.models.entity import DocumentImage, DocumentTable, Message
from app.schemas.chat import (
    ChatAttachmentOut,
    ChatRequest,
    ChatToolOut,
    CitationImageOut,
    CitationOut,
    ConversationCreate,
    ConversationMemoryOut,
    ConversationOut,
    ConversationUpdate,
    FeedbackIn,
    MessageOut,
    ToolActionIn,
    ToolActionOut,
)

logger = get_logger("api.chat")
router = APIRouter(tags=["chat"])


MAX_IMAGES_PER_CITATION = 3


def _image_payload(image) -> dict:
    return {
        "image_id": image.id,
        "url": f"/api/v1/documents/{image.doc_id}/images/{image.id}",
        "caption": image.caption or "",
        "page": image.page,
        "version_id": image.version_id,
    }


async def _attach_citation_images(
    session: AsyncSession, tenant_id: str, citations: list[dict]
) -> None:
    """Attach image evidence to citations: explicit image chunks first, then same-page images."""
    explicit = sorted({item.get("image_id") for item in citations if item.get("image_id")})
    mapping: dict[str, list[dict]] = {}
    if explicit:
        result = await session.execute(
            select(DocumentImage).where(
                DocumentImage.tenant_id == tenant_id, DocumentImage.id.in_(explicit)
            )
        )
        for image in result.scalars():
            mapping.setdefault(image.id, []).append(_image_payload(image))
    for item in citations:
        item["images"] = mapping.get(item.get("image_id") or "", [])

    pending = [
        item
        for item in citations
        if not item["images"] and item.get("doc_id") and int(item.get("page") or 0) > 0
    ]
    heading_pending = [item for item in citations if not item["images"] and item.get("heading_path")]
    if not pending and not heading_pending:
        return
    if not pending:
        pass
    doc_ids = sorted({item["doc_id"] for item in pending}) or [""]
    pages = sorted({int(item.get("page") or 0) for item in pending}) or [0]
    result = await session.execute(
        select(DocumentImage)
        .where(
            DocumentImage.tenant_id == tenant_id,
            DocumentImage.doc_id.in_(doc_ids),
            DocumentImage.page.in_(pages),
        )
        .order_by(DocumentImage.page, DocumentImage.created_at)
    )
    by_key: dict[tuple[str, int], list[dict]] = {}
    for image in result.scalars():
        by_key.setdefault((image.doc_id, image.page), []).append(_image_payload(image))
    for item in pending:
        images = by_key.get((item["doc_id"], int(item.get("page") or 0)), [])
        version_id = item.get("version_id")
        if version_id:
            images = [entry for entry in images if entry["version_id"] == version_id]
        item["images"] = images[:MAX_IMAGES_PER_CITATION]

    if not heading_pending:
        return
    result = await session.execute(
        select(DocumentImage)
        .where(DocumentImage.tenant_id == tenant_id, DocumentImage.heading_path != "")
        .order_by(DocumentImage.created_at)
    )
    by_heading: dict[tuple[str, str], list[dict]] = {}
    for image in result.scalars():
        by_heading.setdefault((image.doc_id, image.heading_path), []).append(_image_payload(image))
    for item in heading_pending:
        images = by_heading.get((item["doc_id"], item["heading_path"]), [])
        version_id = item.get("version_id")
        if version_id:
            images = [entry for entry in images if entry["version_id"] == version_id]
        item["images"] = images[:MAX_IMAGES_PER_CITATION]


async def _attach_citation_tables(
    session: AsyncSession, tenant_id: str, citations: list[dict]
) -> None:
    """Attach the table asset behind a table row/summary citation.

    The citation still points at the retrieved row (D8); the table payload is
    only there so the UI can show the surrounding grid.
    """
    table_ids = sorted({item.get("table_id") for item in citations if item.get("table_id")})
    if not table_ids:
        return
    result = await session.execute(
        select(DocumentTable).where(
            DocumentTable.tenant_id == tenant_id, DocumentTable.id.in_(table_ids)
        )
    )
    mapping = {
        table.id: {
            "table_id": table.id,
            "name": table.name,
            "header": list(table.header or []),
            "row_count": table.row_count,
            "summary": table.summary or "",
            "url": f"/api/v1/documents/{table.doc_id}/tables/{table.id}",
        }
        for table in result.scalars()
    }
    for item in citations:
        payload = mapping.get(item.get("table_id") or "")
        if payload:
            item["table"] = payload


async def _load_citation_images(
    session: AsyncSession, tenant_id: str, image_ids: list[str | None]
) -> dict[str, list[dict]]:
    """Build image payloads for citations so the frontend can display originals."""
    ids = sorted({value for value in image_ids if value})
    if not ids:
        return {}
    result = await session.execute(
        select(DocumentImage).where(DocumentImage.tenant_id == tenant_id, DocumentImage.id.in_(ids))
    )
    mapping: dict[str, list[dict]] = {}
    for image in result.scalars():
        mapping.setdefault(image.id, []).append(
            {
                "image_id": image.id,
                "url": f"/api/v1/documents/{image.doc_id}/images/{image.id}",
                "caption": image.caption or "",
                "page": image.page,
            }
        )
    return mapping


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation_endpoint(
    payload: ConversationCreate | None = None,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> ConversationOut:
    custom = (payload.title if payload else None) or None
    conversation = await create_conversation(
        session,
        tenant_id,
        title=custom,
        created_by=principal.user_id,
        title_source=TITLE_SOURCE_USER if custom else None,
    )
    return ConversationOut.model_validate(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation_endpoint(
    conversation_id: str,
    payload: ConversationUpdate,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> ConversationOut:
    conversation = await update_conversation_title(
        session,
        tenant_id,
        conversation_id,
        payload.title,
        created_by=principal.user_id,
    )
    return ConversationOut.model_validate(conversation)


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations_endpoint(
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> list[ConversationOut]:
    conversations = await list_conversations(session, tenant_id, created_by=principal.user_id)
    return [ConversationOut.model_validate(item) for item in conversations]


@router.get("/chat/tools", response_model=list[ChatToolOut])
async def chat_tools_endpoint(
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> list[ChatToolOut]:
    return [ChatToolOut(**item) for item in list_tools_for_principal(principal)]


@router.post("/chat/attachments", response_model=ChatAttachmentOut, status_code=201)
async def chat_attachments_endpoint(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> ChatAttachmentOut:
    data = await file.read()
    meta = save_chat_xlsx(
        user_id=principal.user_id,
        filename=file.filename or "upload.xlsx",
        data=data,
    )
    return ChatAttachmentOut(
        id=meta["id"], filename=meta["filename"], storage_key=meta["storage_key"]
    )


@router.post("/chat/tool-action", response_model=ToolActionOut)
async def chat_tool_action_endpoint(
    body: ToolActionIn,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> ToolActionOut:
    conversation = await get_conversation(
        session, tenant_id, body.conversation_id, created_by=principal.user_id
    )
    result = await apply_tool_action(
        session,
        principal=principal,
        conversation=conversation,
        action=body.action,
        payload=body.payload,
    )
    await save_user_message(
        session,
        conversation.id,
        tenant_id,
        f"[工具动作] {body.action}",
    )
    meta = {"card": result.get("card")} if result.get("card") else None
    await save_assistant_turn(
        session,
        conversation.id,
        tenant_id,
        result["content"],
        rewritten_query=None,
        citations=[],
        meta=meta,
    )
    await session.commit()
    return ToolActionOut(
        content=result["content"],
        card=result.get("card"),
        conversation_id=conversation.id,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def messages_endpoint(
    conversation_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> list[MessageOut]:
    rows = await list_messages(
        session, tenant_id, conversation_id, created_by=principal.user_id
    )
    image_map = await _load_citation_images(
        session, tenant_id, [item.image_id for _, citations in rows for item in citations]
    )
    output: list[MessageOut] = []
    for message, citations in rows:
        output.append(
            MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                rewritten_query=message.rewritten_query,
                compressed=bool(message.compressed),
                meta=message.meta,
                citations=[
                    CitationOut(
                        chunk_id=item.chunk_id,
                        doc_id=item.doc_id,
                        document_title=item.document_title,
                        page=item.page,
                        section=item.section,
                        images=[
                            CitationImageOut(**entry) for entry in image_map.get(item.image_id or "", [])
                        ],
                    )
                    for item in citations
                ],
                created_at=message.created_at,
            )
        )
    return output


@router.get("/conversations/{conversation_id}/memory", response_model=ConversationMemoryOut | None)
async def conversation_memory_endpoint(
    conversation_id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> ConversationMemoryOut | None:
    summary = await get_latest_conversation_summary(
        session, tenant_id, conversation_id, created_by=principal.user_id
    )
    if summary is None:
        return None
    return ConversationMemoryOut(
        conversation_id=summary.conversation_id,
        content=summary.content,
        version=summary.version,
        token_count=summary.token_count,
        covered_from_message_id=summary.covered_from_message_id,
        covered_to_message_id=summary.covered_to_message_id,
        updated_at=summary.updated_at,
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> StreamingResponse:
    redis = get_redis()
    client_key = request.client.host if request.client else "unknown"
    allowed, _ = await check_rate_limit(redis, f"{tenant_id}:{client_key}")
    if not allowed:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    graph: ChatGraph = request.app.state.chat_graph
    bind_context(
        tenant_id=tenant_id,
        user_id=principal.user_id,
        conversation_id=payload.conversation_id,
    )
    # StreamingResponse body runs after middleware clears contextvars; snapshot now.
    log_ctx = get_log_context()
    return StreamingResponse(
        _chat_event_stream(graph, payload, tenant_id, principal, log_ctx=log_ctx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _chat_event_stream(
    graph: ChatGraph,
    payload: ChatRequest,
    tenant_id: str,
    principal: Principal,
    *,
    log_ctx: dict | None = None,
) -> AsyncIterator[str]:
    with logging_context(**(log_ctx or {})):
        async for chunk in _chat_event_stream_inner(graph, payload, tenant_id, principal):
            yield chunk


async def _chat_event_stream_inner(
    graph: ChatGraph, payload: ChatRequest, tenant_id: str, principal: Principal
) -> AsyncIterator[str]:
    session_factory = get_session_factory()
    try:
        # Phase 1: short-lived session for conversation + user message (+ tool route).
        async with session_factory() as session:
            attachment = None
            filename = None
            if payload.attachment_id:
                attachment = load_attachment(
                    payload.attachment_id, user_id=principal.user_id
                )
                filename = attachment["filename"]

            polish_title: str | None = None
            if payload.conversation_id:
                conversation = await get_conversation(
                    session, tenant_id, payload.conversation_id, created_by=principal.user_id
                )
            else:
                rule = derive_rule_title(payload.message, filename)
                conversation = await create_conversation(
                    session,
                    tenant_id,
                    title=rule,
                    created_by=principal.user_id,
                    title_source=TITLE_SOURCE_AUTO if rule != "新对话" else None,
                )
                clear_tool_state(conversation)
                if conversation.title_source == TITLE_SOURCE_AUTO:
                    polish_title = conversation.title

            conversation_id = conversation.id
            bind_context(conversation_id=conversation_id)
            log_event(
                logger,
                "chat start",
                event="chat.start",
                query_preview=preview_text(payload.message),
            )
            yield sse_event({"event": "message_start", "data": {"conversation_id": conversation_id}})

            # Auto-title: rule first when still default, then enqueue LLM polish.
            new_title = apply_rule_title_if_default(
                conversation, message=payload.message, filename=filename
            )
            if new_title:
                await session.commit()
                polish_title = new_title
            if polish_title:
                try:
                    await maybe_enqueue_title_polish(
                        get_redis(),
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        rule_title=polish_title,
                    )
                except Exception:
                    logger.warning("title polish enqueue failed", exc_info=True)

            # Explicit tool selection updates conversation state; "" clears sticky tool.
            if payload.active_tool:
                update_staffing_state(conversation, active_tool=payload.active_tool)
            elif payload.active_tool == "":
                state = dict(conversation.tool_state or {})
                state.pop("active_tool", None)
                set_tool_state(conversation, state or None)

            state = dict(conversation.tool_state or {})
            pending_clarify = bool(state.get("pending_clarify"))
            active_from_state = state.get("active_tool")
            if payload.active_tool == "":
                active_tool = None
            elif payload.active_tool is not None:
                active_tool = payload.active_tool
            else:
                active_tool = active_from_state

            if pending_clarify and user_affirms_staffing(payload.message):
                decision_kind = "staffing"
                auto_note = "已确认使用人员投入。"
                state.pop("pending_clarify", None)
                set_tool_state(conversation, state)
                update_staffing_state(conversation, active_tool="staffing")
            elif pending_clarify and user_declines_staffing(payload.message):
                decision_kind = "none"
                auto_note = None
                state.pop("pending_clarify", None)
                set_tool_state(conversation, state)
            else:
                decision = route_turn(
                    principal,
                    active_tool=active_tool,
                    message=payload.message,
                    filename=filename,
                )
                decision_kind = decision.kind
                auto_note = (
                    "已按人员投入处理。" if decision.reason == "strong_rules" else None
                )

            settings = get_settings()
            ctx = await build_chat_context(
                session,
                tenant_id,
                conversation_id,
                history_turns=settings.history_turns,
            )
            user_message = await save_user_message(
                session, conversation_id, tenant_id, payload.message
            )
            await session.commit()

            if decision_kind == "clarify":
                content = WEAK_CLARIFY_COPY
                state = dict(conversation.tool_state or {})
                state["pending_clarify"] = True
                set_tool_state(conversation, state)
                assistant_message = await save_assistant_turn(
                    session,
                    conversation_id,
                    tenant_id,
                    content,
                    rewritten_query=None,
                    citations=[],
                    meta={"tool": "staffing", "clarify": True},
                )
                await session.commit()
                yield sse_event({"event": "token", "data": content})
                yield sse_event(
                    {
                        "event": "done",
                        "data": {
                            "conversation_id": conversation_id,
                            "message_id": assistant_message.id,
                            "answer": content,
                            "citations": [],
                            "card": None,
                            "error": None,
                        },
                    }
                )
                return

            if decision_kind == "staffing":
                try:
                    result = await handle_staffing_message(
                        session,
                        principal=principal,
                        conversation=conversation,
                        message=payload.message,
                        attachment=attachment,
                        auto_note=auto_note,
                    )
                except AppError as exc:
                    content = exc.message
                    result = {"content": content, "card": None}
                content = result["content"]
                card = result.get("card")
                meta = {"tool": "staffing", "card": card} if card else {"tool": "staffing"}
                assistant_message = await save_assistant_turn(
                    session,
                    conversation_id,
                    tenant_id,
                    content,
                    rewritten_query=None,
                    citations=[],
                    meta=meta,
                )
                await session.commit()
                yield sse_event({"event": "token", "data": content})
                yield sse_event(
                    {
                        "event": "done",
                        "data": {
                            "conversation_id": conversation_id,
                            "message_id": assistant_message.id,
                            "answer": content,
                            "citations": [],
                            "card": card,
                            "error": None,
                        },
                    }
                )
                log_event(
                    logger,
                    "chat staffing done",
                    event="chat.tool.staffing",
                    ok=True,
                )
                return

        config = {"configurable": {"thread_id": conversation_id}}
        input_state = {
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "user_question": payload.message,
            "memory_summary": ctx.get("memory_summary") or "",
            "history": list(ctx["history"]) + [{"role": "user", "content": payload.message}],
            "principal_scope": {
                "user_id": principal.user_id,
                "username": principal.username,
                "display_name": principal.display_name,
                "site": principal.site,
                "clearance": principal.clearance,
                "org_unit_ids": list(principal.org_unit_ids),
                "domains": list(principal.domains),
                "project_ids": list(principal.project_ids),
                "permissions": list(principal.permissions),
            },
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
        answer = values.get("answer") or ""
        if not answer:
            if error_detail:
                answer = f"回答生成失败：{error_detail}"
            else:
                answer = "（未生成回答）"
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
                actor=principal.username,
            )
            try:
                await maybe_enqueue_compress_for_conversation(
                    session,
                    get_redis(),
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.exception("Failed to enqueue memory compress for %s", conversation_id)
        async with session_factory() as session:
            await _attach_citation_images(session, tenant_id, citations)
            await _attach_citation_tables(session, tenant_id, citations)

        yield sse_event(
            {
                "event": "done",
                "data": {
                    "conversation_id": conversation_id,
                    "message_id": assistant_message.id,
                    "answer": answer,
                    "citations": citations,
                    "card": None,
                    "error": error_detail,
                },
            }
        )
        log_event(
            logger,
            "chat done",
            event="chat.done",
            ok=error_detail is None,
            citation_count=len(citations),
            refused=bool(values.get("refused")),
        )
    except AppError as exc:
        yield sse_event({"event": "error", "data": exc.message})


@router.post("/feedback", status_code=201)
async def submit_feedback(
    payload: FeedbackIn,
    session: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(tenant_from_principal),
    principal: Principal = Depends(require_permission(PERM_CHAT_USE)),
) -> dict:
    feedback = await save_feedback(session, tenant_id, payload.message_id, payload.rating, payload.comment)
    return {"id": feedback.id, "message_id": feedback.message_id, "rating": feedback.rating}
