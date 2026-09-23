"""Conversation title: rule derivation, apply, and async LLM polish."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.entity import Conversation, Message
from app.providers.base import LLMProvider

logger = get_logger("chat.title")

DEFAULT_TITLE = "新对话"
TITLE_SOURCE_DEFAULT = "default"
TITLE_SOURCE_AUTO = "auto"
TITLE_SOURCE_USER = "user"
MAX_TITLE_LEN = 30
MAX_POLISH_LEN = 20

_WS = re.compile(r"\s+")


def derive_rule_title(message: str, filename: str | None = None) -> str:
    """Build a short sidebar title from first user text or attachment name."""
    text = _WS.sub(" ", (message or "").strip())
    if not text:
        stem = Path(filename or "").stem.strip() if filename else ""
        text = _WS.sub(" ", stem)
    if not text:
        return DEFAULT_TITLE
    if len(text) > MAX_TITLE_LEN:
        text = text[:MAX_TITLE_LEN].rstrip()
    return text or DEFAULT_TITLE


def sanitize_polished_title(raw: str) -> str | None:
    text = (raw or "").strip().strip("「」『』\"'“”")
    text = _WS.sub(" ", text)
    if not text:
        return None
    # Take first line only
    text = text.splitlines()[0].strip()
    if len(text) > MAX_POLISH_LEN:
        text = text[:MAX_POLISH_LEN].rstrip()
    if not text or text == DEFAULT_TITLE:
        return None
    return text


def apply_rule_title_if_default(
    conversation: Conversation,
    *,
    message: str,
    filename: str | None = None,
) -> str | None:
    """Set rule title when still default. Returns new title or None if unchanged."""
    source = getattr(conversation, "title_source", None) or TITLE_SOURCE_DEFAULT
    if source != TITLE_SOURCE_DEFAULT:
        return None
    title = derive_rule_title(message, filename)
    if title == DEFAULT_TITLE:
        return None
    conversation.title = title
    conversation.title_source = TITLE_SOURCE_AUTO
    return title


def make_title_polish_job(
    *,
    conversation_id: str,
    tenant_id: str,
    rule_title: str,
    enqueued_at_ms: int | None = None,
) -> str:
    return json.dumps(
        {
            "type": "title_polish",
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "rule_title": rule_title,
            "enqueued_at_ms": enqueued_at_ms or int(time.time() * 1000),
        },
        ensure_ascii=False,
    )


async def enqueue_title_polish(redis: Redis, job: str) -> None:
    settings = get_settings()
    await redis.rpush(settings.memory_queue_key, job)


async def maybe_enqueue_title_polish(
    redis: Redis | None,
    *,
    conversation_id: str,
    tenant_id: str,
    rule_title: str,
) -> bool:
    if redis is None:
        return False
    try:
        job = make_title_polish_job(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            rule_title=rule_title,
        )
        await enqueue_title_polish(redis, job)
        log_event(
            logger,
            "title polish enqueued",
            event="title.polish_enqueued",
            conversation_id=conversation_id,
        )
        return True
    except RedisError:
        logger.warning("Redis unavailable for title polish enqueue", exc_info=True)
        return False


async def run_title_polish_job(
    session: AsyncSession,
    llm: LLMProvider,
    job: dict,
) -> bool:
    conversation_id = str(job.get("conversation_id") or "")
    tenant_id = str(job.get("tenant_id") or "")
    rule_title = str(job.get("rule_title") or "")
    if not conversation_id or not tenant_id:
        return False

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant_id:
        return False
    if conversation.title_source != TITLE_SOURCE_AUTO:
        log_event(
            logger,
            "title polish skipped (not auto)",
            event="title.polish_skipped",
            conversation_id=conversation_id,
            title_source=conversation.title_source,
        )
        return False

    try:
        raw = await llm.complete(
            system=(
                "你是会话标题助手。根据用户首条内容，生成一个简短中文对话标题。"
                f"要求：8–{MAX_POLISH_LEN}字，不要引号、不要句号、不要解释，只输出标题本身。"
            ),
            user=f"首条内容：{rule_title}",
            temperature=0.3,
        )
        polished = sanitize_polished_title(raw)
    except Exception:
        logger.exception("Title polish LLM failed for %s", conversation_id)
        log_event(
            logger,
            "title polish failed",
            event="title.polish_failed",
            conversation_id=conversation_id,
        )
        return False

    if not polished:
        return False

    # Re-check race with user rename
    await session.refresh(conversation)
    if conversation.title_source != TITLE_SOURCE_AUTO:
        return False

    conversation.title = polished
    conversation.title_source = TITLE_SOURCE_AUTO
    await session.commit()
    log_event(
        logger,
        "title polish done",
        event="title.polish_done",
        conversation_id=conversation_id,
        title_preview=polished[:40],
    )
    return True


async def backfill_default_titles(
    session: AsyncSession, *, tenant_id: str | None = None, limit: int = 500
) -> int:
    """Rule-title conversations still on default that already have a user message."""
    stmt = select(Conversation).where(
        Conversation.title_source == TITLE_SOURCE_DEFAULT,
        Conversation.title == DEFAULT_TITLE,
    )
    if tenant_id:
        stmt = stmt.where(Conversation.tenant_id == tenant_id)
    stmt = stmt.limit(limit)
    conversations = list((await session.execute(stmt)).scalars())
    updated = 0
    for conv in conversations:
        msg = (
            await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role == "user",
                )
                .order_by(Message.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not msg:
            continue
        title = derive_rule_title(msg.content, None)
        if title == DEFAULT_TITLE:
            continue
        conv.title = title
        conv.title_source = TITLE_SOURCE_AUTO
        updated += 1
    if updated:
        await session.commit()
    return updated
