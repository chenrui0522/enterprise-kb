from __future__ import annotations

import time

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.memory.context import get_latest_summary, list_uncompressed_messages, window_token_total
from app.chat.memory.queue import (
    acquire_compress_lock,
    maybe_enqueue_compress,
    release_compress_lock,
)
from app.chat.memory.tokens import estimate_tokens, truncate_to_token_cap
from app.core.config import get_settings
from app.core.logging import get_logger, log_event, preview_text
from app.models.entity import ConversationSummary
from app.providers.base import LLMProvider

logger = get_logger("chat.memory.compress")

SUMMARY_SYSTEM = """你是企业知识库的会话记忆压缩器。
将【已有摘要】与【新滑出的对话】合并成一段简洁的滚动摘要，供后续多轮问答使用。
要求：
1. 保留关键实体、型号、编号、人名、结论与未决事项；不要编造。
2. 去掉寒暄与重复内容；使用中文短句。
3. 只输出 JSON：{"summary": "摘要正文"}。"""


async def maybe_enqueue_compress_for_conversation(
    session: AsyncSession,
    redis: Redis,
    *,
    tenant_id: str,
    conversation_id: str,
) -> bool:
    uncompressed = await list_uncompressed_messages(session, tenant_id, conversation_id)
    tokens = await window_token_total(uncompressed)
    return await maybe_enqueue_compress(
        redis,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        window_tokens=tokens,
    )


async def run_compress_job(
    session: AsyncSession,
    redis: Redis,
    llm: LLMProvider,
    job: dict,
) -> ConversationSummary | None:
    conversation_id = str(job.get("conversation_id") or "")
    tenant_id = str(job.get("tenant_id") or "")
    enqueued_at = int(job.get("enqueued_at_ms") or 0)
    if not conversation_id or not tenant_id:
        return None

    if not await acquire_compress_lock(redis, conversation_id):
        log_event(
            logger,
            "memory compress skipped lock",
            event="memory.compress_failed",
            conversation_id=conversation_id,
            error="lock_not_acquired",
        )
        return None

    try:
        return await _compress_locked(
            session, llm, tenant_id=tenant_id, conversation_id=conversation_id, enqueued_at=enqueued_at
        )
    except Exception as exc:
        log_event(
            logger,
            "memory compress failed",
            event="memory.compress_failed",
            conversation_id=conversation_id,
            error=preview_text(str(exc), limit=200),
        )
        raise
    finally:
        await release_compress_lock(redis, conversation_id)


async def _compress_locked(
    session: AsyncSession,
    llm: LLMProvider,
    *,
    tenant_id: str,
    conversation_id: str,
    enqueued_at: int,
) -> ConversationSummary | None:
    settings = get_settings()
    uncompressed = await list_uncompressed_messages(session, tenant_id, conversation_id)
    window_tokens = await window_token_total(uncompressed)
    if window_tokens <= settings.memory_token_budget:
        log_event(
            logger,
            "memory compress noop under budget",
            event="memory.budget_check",
            conversation_id=conversation_id,
            window_tokens=window_tokens,
            budget=settings.memory_token_budget,
            over_budget=False,
        )
        return None

    keep = max(1, settings.history_turns * 2)
    if len(uncompressed) <= keep:
        # Over budget but cannot free a full turn window; compress oldest half.
        split = max(1, len(uncompressed) // 2)
        to_compress = uncompressed[:split]
        retain = uncompressed[split:]
    else:
        to_compress = uncompressed[:-keep]
        retain = uncompressed[-keep:]

    if not to_compress:
        return None

    previous = await get_latest_summary(session, tenant_id, conversation_id)
    old_text = previous.content if previous else ""
    transcript = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}: {m.content}" for m in to_compress
    )
    payload = await llm.complete_json(
        system=SUMMARY_SYSTEM,
        user=f"【已有摘要】\n{old_text or '（无）'}\n\n【新滑出的对话】\n{transcript}",
        temperature=0.1,
    )
    summary_text = str(payload.get("summary") or "").strip()
    if not summary_text:
        summary_text = (old_text + "\n" + transcript).strip()
    summary_text, capped = truncate_to_token_cap(summary_text, settings.summary_token_cap)
    summary_tokens = estimate_tokens(summary_text)
    version = (previous.version + 1) if previous else 1

    row = ConversationSummary(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        covered_from_message_id=to_compress[0].id,
        covered_to_message_id=to_compress[-1].id,
        content=summary_text,
        token_count=summary_tokens,
        version=version,
    )
    session.add(row)
    await session.flush()

    for message in to_compress:
        message.compressed = True
        message.summary_id = row.id
        if not message.token_count:
            message.token_count = estimate_tokens(message.content)

    await session.commit()
    await session.refresh(row)

    lag_ms = int(time.time() * 1000) - enqueued_at if enqueued_at else None
    log_event(
        logger,
        "memory compress done",
        event="memory.compress_done",
        conversation_id=conversation_id,
        covered_from=row.covered_from_message_id,
        covered_to=row.covered_to_message_id,
        summary_tokens=summary_tokens,
        capped=capped,
        version=version,
        retained_messages=len(retain),
        **({"memory.compress_lag_ms": lag_ms} if lag_ms is not None and lag_ms >= 0 else {}),
    )
    if lag_ms is not None and lag_ms >= 0:
        log_event(
            logger,
            "memory compress lag",
            event="memory.compress_lag_ms",
            conversation_id=conversation_id,
            lag_ms=lag_ms,
        )
    return row


# Re-export for callers that import from compress module
__all__ = [
    "maybe_enqueue_compress_for_conversation",
    "run_compress_job",
]
