"""Conversation memory: budget, async compress, L1 events, L2 entity probe."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.graph import ChatGraph
from app.chat.memory.compress import maybe_enqueue_compress_for_conversation, run_compress_job
from app.chat.memory.context import build_chat_context
from app.chat.memory.queue import maybe_enqueue_compress
from app.chat.memory.tokens import estimate_tokens, truncate_to_token_cap
from app.core.config import get_settings
from app.core.db import Base
from app.core.logging import setup_logging
from app.models.entity import Conversation, Message
from app.providers.base import LLMProvider


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.kv: dict[str, str] = {}

    async def rpush(self, key: str, *values: str) -> int:
        bucket = self.lists.setdefault(key, [])
        bucket.extend(values)
        return len(bucket)

    async def lpop(self, key: str) -> str | None:
        bucket = self.lists.get(key) or []
        if not bucket:
            return None
        return bucket.pop(0)

    async def lrem(self, key: str, count: int, value: str) -> int:  # noqa: ARG002
        bucket = self.lists.get(key) or []
        removed = 0
        while value in bucket:
            bucket.remove(value)
            removed += 1
            if count > 0 and removed >= count:
                break
        return removed

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        bucket = self.lists.get(key) or []
        if end == -1:
            end = len(bucket) - 1
        return bucket[start : end + 1]

    async def delete(self, key: str) -> int:
        existed = key in self.lists or key in self.kv
        self.lists.pop(key, None)
        self.kv.pop(key, None)
        return int(existed)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:  # noqa: ARG002
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True


class SummaryLLM(LLMProvider):
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.calls: list[dict] = []

    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        return self.summary

    async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
        self.calls.append({"system": system, "user": user})
        return {"summary": self.summary}

    async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
        yield self.summary
        return


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_estimate_tokens_and_cap() -> None:
    assert estimate_tokens("abcd") == 2
    text, capped = truncate_to_token_cap("你好世界测试摘要内容" * 50, 10)
    assert capped is True
    assert estimate_tokens(text) <= 12  # allow ellipsis slack


@pytest.mark.asyncio
async def test_budget_check_enqueues_when_over(monkeypatch, capsys) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("KB_MEMORY_TOKEN_BUDGET", "100")
    get_settings.cache_clear()
    redis = FakeRedis()
    setup_logging()
    enqueued = await maybe_enqueue_compress(
        redis,  # type: ignore[arg-type]
        conversation_id="c1",
        tenant_id="t1",
        window_tokens=250,
    )
    assert enqueued is True
    settings = get_settings()
    assert redis.lists[settings.memory_queue_key]
    payload = json.loads(redis.lists[settings.memory_queue_key][0])
    assert payload["type"] == "memory_compress"
    out = capsys.readouterr().out
    assert "memory.budget_check" in out
    assert "memory.compress_enqueued" in out
    assert '"window_tokens": 250' in out
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compress_marks_messages_and_keeps_original(
    session_factory, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("KB_MEMORY_TOKEN_BUDGET", "50")
    monkeypatch.setenv("KB_SUMMARY_TOKEN_CAP", "200")
    monkeypatch.setenv("KB_HISTORY_TURNS", "1")
    get_settings.cache_clear()

    entity = "审批人张三丰"
    async with session_factory() as session:
        conversation = Conversation(tenant_id="t1", title="probe", created_by="u1")
        session.add(conversation)
        await session.commit()
        await session.refresh(conversation)
        cid = conversation.id
        # Long early turns that should compress out
        for index in range(4):
            content = f"{entity} 负责报销审批。轮次{index}。" + ("详述" * 40)
            session.add(
                Message(
                    tenant_id="t1",
                    conversation_id=cid,
                    role="user" if index % 2 == 0 else "assistant",
                    content=content,
                    compressed=False,
                    token_count=estimate_tokens(content),
                )
            )
        await session.commit()

    redis = FakeRedis()
    llm = SummaryLLM(f"会话记忆：{entity}负责报销审批。")
    setup_logging()
    async with session_factory() as session:
        await maybe_enqueue_compress_for_conversation(
            session, redis, tenant_id="t1", conversation_id=cid  # type: ignore[arg-type]
        )
        raw = (redis.lists.get(get_settings().memory_queue_key) or [None])[0]
        assert raw
        job = json.loads(raw)
        summary = await run_compress_job(session, redis, llm, job)  # type: ignore[arg-type]

    assert summary is not None
    assert entity in summary.content
    out = capsys.readouterr().out
    assert "memory.compress_done" in out

    async with session_factory() as session:
        result = await session.execute(select(Message).where(Message.conversation_id == cid))
        rows = list(result.scalars())
        assert any(m.compressed for m in rows)
        assert all(m.content for m in rows)  # originals retained
        ctx = await build_chat_context(session, "t1", cid, history_turns=1)
        assert ctx["memory_summary"] and entity in ctx["memory_summary"]
        assert all(item["content"] for item in ctx["history"])

    # DB is source of truth: clearing redis does not drop summary
    redis.lists.clear()
    redis.kv.clear()
    async with session_factory() as session:
        ctx = await build_chat_context(session, "t1", cid, history_turns=1)
        assert entity in (ctx["memory_summary"] or "")

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rewrite_uses_memory_summary() -> None:
    class CapturingLLM(LLMProvider):
        def __init__(self) -> None:
            self.last_user = ""

        async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
            return "ok"

        async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
            self.last_user = user
            if "查询改写器" in system:
                return {"rewritten_query": "张三丰审批权限"}
            if "是否需要查询" in system:
                return {"need_retrieval": False, "reason": "基于摘要"}
            return {}

        async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
            yield "基于摘要回答"
            return

    class EmptySearch:
        async def search(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return []

    llm = CapturingLLM()
    graph = ChatGraph(llm, EmptySearch(), history_turns=2).graph  # type: ignore[arg-type]
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "他还负责什么",
            "memory_summary": "审批人张三丰负责报销。",
            "history": [],
        }
    )
    assert "会话记忆摘要" in llm.last_user
    assert "张三丰" in llm.last_user
    assert result["rewritten_query"] == "张三丰审批权限"


@pytest.mark.asyncio
async def test_graph_degrades_without_summary() -> None:
    class FakeLLM(LLMProvider):
        async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
            return "你好"

        async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
            return {"rewritten_query": "你好", "need_retrieval": False}

        async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
            yield "hi"
            return

    class EmptySearch:
        async def search(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return []

    graph = ChatGraph(FakeLLM(), EmptySearch()).graph  # type: ignore[arg-type]
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "你好",
            "history": [],
        }
    )
    assert result["answer"]
