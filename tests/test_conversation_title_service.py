"""Integration: rename API, rule title apply, polish race."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.service import create_conversation, update_conversation_title
from app.chat.title import (
    TITLE_SOURCE_AUTO,
    TITLE_SOURCE_DEFAULT,
    TITLE_SOURCE_USER,
    apply_rule_title_if_default,
    backfill_default_titles,
    run_title_polish_job,
)
from app.core.db import Base
from app.core.errors import AppError
from app.models.entity import Message
import app.models.entity  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.staffing  # noqa: F401


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        return self.reply


@pytest.mark.asyncio
async def test_update_title_sets_user_source(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        assert conv.title_source == TITLE_SOURCE_DEFAULT
        updated = await update_conversation_title(
            session, "t1", conv.id, "自定义标题", created_by="u1"
        )
        assert updated.title == "自定义标题"
        assert updated.title_source == TITLE_SOURCE_USER
        with pytest.raises(AppError):
            await update_conversation_title(session, "t1", conv.id, "  ", created_by="u1")
    await engine.dispose()


@pytest.mark.asyncio
async def test_polish_respects_user_rename(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        apply_rule_title_if_default(conv, message="打印机保修多久")
        await session.commit()
        await update_conversation_title(session, "t1", conv.id, "手改名", created_by="u1")
        ok = await run_title_polish_job(
            session,
            _FakeLLM("保修咨询"),
            {
                "conversation_id": conv.id,
                "tenant_id": "t1",
                "rule_title": "打印机保修多久",
            },
        )
        assert ok is False
        await session.refresh(conv)
        assert conv.title == "手改名"
        assert conv.title_source == TITLE_SOURCE_USER
    await engine.dispose()


@pytest.mark.asyncio
async def test_polish_replaces_auto_title(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        apply_rule_title_if_default(conv, message="打印机保修多久")
        await session.commit()
        ok = await run_title_polish_job(
            session,
            _FakeLLM("保修咨询"),
            {
                "conversation_id": conv.id,
                "tenant_id": "t1",
                "rule_title": "打印机保修多久",
            },
        )
        assert ok is True
        await session.refresh(conv)
        assert conv.title == "保修咨询"
        assert conv.title_source == TITLE_SOURCE_AUTO
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_default_titles(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        session.add(
            Message(
                tenant_id="t1",
                conversation_id=conv.id,
                role="user",
                content="费用报销要谁批",
            )
        )
        await session.commit()
        n = await backfill_default_titles(session, tenant_id="t1")
        assert n == 1
        await session.refresh(conv)
        assert conv.title == "费用报销要谁批"
        assert conv.title_source == TITLE_SOURCE_AUTO
    await engine.dispose()
