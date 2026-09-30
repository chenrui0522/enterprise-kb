"""Hard-delete conversation: ownership, cascade, checkpoint best-effort."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.service import (
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
)
from app.core.db import Base
from app.core.errors import NotFoundError
from app.models.entity import ConversationSummary, Message
import app.models.entity  # noqa: F401
import app.models.identity  # noqa: F401
import app.models.staffing  # noqa: F401
import app.models.leave_ledger  # noqa: F401


async def _engine(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_conn, _connection_record):  # noqa: ARG001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_delete_own_conversation_cascades_messages(tmp_path) -> None:
    engine = await _engine(tmp_path, "del.sqlite")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        session.add(
            Message(
                tenant_id="t1",
                conversation_id=conv.id,
                role="user",
                content="hello",
            )
        )
        session.add(
            ConversationSummary(
                tenant_id="t1",
                conversation_id=conv.id,
                content="摘要",
                version=1,
            )
        )
        await session.commit()
        cid = conv.id
        await delete_conversation(session, "t1", cid, created_by="u1")
        with pytest.raises(NotFoundError):
            await get_conversation(session, "t1", cid, created_by="u1")
        rows = await list_conversations(session, "t1", created_by="u1")
        assert all(r.id != cid for r in rows)
        msgs = await session.execute(select(Message).where(Message.conversation_id == cid))
        assert list(msgs.scalars()) == []
        sums = await session.execute(
            select(ConversationSummary).where(ConversationSummary.conversation_id == cid)
        )
        assert list(sums.scalars()) == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_others_conversation_not_found(tmp_path) -> None:
    engine = await _engine(tmp_path, "own.sqlite")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        with pytest.raises(NotFoundError):
            await delete_conversation(session, "t1", conv.id, created_by="u2")
        still = await get_conversation(session, "t1", conv.id, created_by="u1")
        assert still.id == conv.id
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_missing_conversation(tmp_path) -> None:
    engine = await _engine(tmp_path, "miss.sqlite")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        with pytest.raises(NotFoundError):
            await delete_conversation(session, "t1", "no-such-id", created_by="u1")
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_messages_after_delete_fails(tmp_path) -> None:
    engine = await _engine(tmp_path, "lm.sqlite")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conv = await create_conversation(session, "t1", created_by="u1")
        cid = conv.id
        await delete_conversation(session, "t1", cid, created_by="u1")
        with pytest.raises(NotFoundError):
            await list_messages(session, "t1", cid, created_by="u1")
    await engine.dispose()
