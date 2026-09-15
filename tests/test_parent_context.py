from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.graph import ChatGraph
from app.chat.parent_context import expand_hits, truncate_text
from app.core.config import Settings
from app.core.db import Base
from app.models.entity import ChunkParent
from app.retrieval.chunk import SearchHit
from app.retrieval.milvus_store import build_filter_expr
from app.retrieval.service import SearchService


def _hit(**overrides) -> dict:
    base = {
        "chunk_id": "c1",
        "doc_id": "d1",
        "version_id": "v1",
        "title": "员工手册",
        "page": 3,
        "section": "考勤",
        "text": "子块命中文本",
        "score": 0.9,
        "chunk_kind": "child",
        "parent_id": "v1-p0000",
    }
    base.update(overrides)
    return base


@asynccontextmanager
async def _session_with_parents(rows: list[ChunkParent]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            for row in rows:
                session.add(row)
            await session.commit()
            yield session
    finally:
        await engine.dispose()


def _parent(parent_id: str, text: str, version_id: str = "v1") -> ChunkParent:
    return ChunkParent(
        id=parent_id,
        tenant_id="t1",
        doc_id="d1",
        version_id=version_id,
        section="考勤",
        heading_path="第一章 > 考勤",
        text=text,
        char_count=len(text),
    )


@pytest.mark.asyncio
async def test_parent_expansion_is_deduplicated() -> None:
    async with _session_with_parents(
        [_parent("v1-p0000", "父块完整正文，包含更多上下文。")]
    ) as session:
        hits = [_hit(chunk_id="c1"), _hit(chunk_id="c2")]
        expanded = await expand_hits(session, hits, token_budget=1000, max_parents=5)
    assert {hit["context_text"] for hit in expanded} == {"父块完整正文，包含更多上下文。"}
    assert all(hit["context_source"] == "parent" for hit in expanded)


@pytest.mark.asyncio
async def test_self_contained_chunks_never_expand() -> None:
    async with _session_with_parents([_parent("v1-p0000", "父块正文")]) as session:
        hits = [
            _hit(chunk_kind="table_row", text="【花名册】姓名=张三"),
            _hit(chunk_kind="table_summary", text="表：花名册；共 2 行"),
            _hit(chunk_kind="image", text="接线图"),
        ]
        expanded = await expand_hits(session, hits, token_budget=1000, max_parents=5)
    assert [hit["context_source"] for hit in expanded] == ["child", "child", "child"]
    assert expanded[0]["context_text"] == "【花名册】姓名=张三"


@pytest.mark.asyncio
async def test_missing_parent_falls_back_to_child_text() -> None:
    async with _session_with_parents([]) as session:
        hits = [_hit(parent_id="missing-parent")]
        expanded = await expand_hits(session, hits, token_budget=1000, max_parents=5)
    assert expanded[0]["context_source"] == "child"
    assert expanded[0]["context_text"] == "子块命中文本"


@pytest.mark.asyncio
async def test_parent_context_respects_token_budget() -> None:
    long_text = "很长的父块内容。" * 500
    async with _session_with_parents([_parent("v1-p0000", long_text)]) as session:
        expanded = await expand_hits(session, [_hit()], token_budget=100, max_parents=5)
    context = expanded[0]["context_text"]
    assert context.endswith("…")
    assert len(context) <= 100 * 2


def test_truncate_text_keeps_short_text() -> None:
    assert truncate_text("短文本", 10) == "短文本"


def test_filter_expr_is_tenant_scoped_by_default() -> None:
    assert build_filter_expr("t1") == 'tenant_id == "t1"'


def test_filter_expr_supports_metadata_filters() -> None:
    expr = build_filter_expr(
        "t1",
        {
            "doc_type": "policy",
            "heading_path": "第一章",
            "chunk_kind": ["child", "table_row"],
            "page": 3,
            "unknown_field": "ignored",
            "table_id": "",
        },
    )
    assert 'tenant_id == "t1"' in expr
    assert 'doc_type == "policy"' in expr
    assert 'heading_path like "第一章%"' in expr
    assert 'chunk_kind in ["child", "table_row"]' in expr
    assert "page == 3" in expr
    assert "unknown_field" not in expr
    assert "table_id" not in expr


def test_filter_expr_escapes_quotes() -> None:
    expr = build_filter_expr("t1", {"doc_type": 'po"licy'})
    assert 'doc_type == "policy"' in expr


def test_retrieval_cache_key_includes_filters() -> None:
    service = SearchService(
        Settings(milvus_uri="http://localhost:19530"),
        store=None,
        embedder=None,
        reranker=None,
        redis=None,
    )
    plain = service._cache_key("考勤", "t1", 20, 3)
    filtered = service._cache_key("考勤", "t1", 20, 3, {"doc_type": "policy"})
    assert plain != filtered
    assert plain == service._cache_key("考勤", "t1", 20, 3, {})


class _FakeLLM:
    def __init__(self) -> None:
        self.systems: list[str] = []

    async def complete(self, *, system: str, user: str, temperature=None) -> str:  # noqa: ARG002
        return "好的。"

    async def complete_json(self, *, system: str, user: str, temperature=None) -> dict:  # noqa: ARG002
        if "查询改写器" in system:
            return {"rewritten_query": "考勤规定"}
        return {"need_retrieval": True, "reason": "需要文档"}

    async def stream(self, *, system: str, user: str, temperature=None):  # noqa: ARG002
        self.systems.append(system)
        yield "依据资料"


class _FakeSearch:
    async def search(self, query, tenant_id, filters=None):  # noqa: ARG002
        return [
            SearchHit(
                chunk_id="c1",
                doc_id="d1",
                version_id="v1",
                title="员工手册",
                page=3,
                section="考勤",
                text="子块命中文本",
                score=0.9,
                parent_id="v1-p0000",
            )
        ]


@pytest.mark.asyncio
async def test_generation_uses_parent_context_but_cites_child() -> None:
    llm = _FakeLLM()

    async def expander(hits: list[dict]) -> list[dict]:
        for hit in hits:
            hit["context_text"] = "父块完整上下文，含全部条款内容。"
        return hits

    graph = ChatGraph(llm, _FakeSearch(), parent_expander=expander).graph
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "考勤怎么规定的？",
            "history": [],
        }
    )
    assert llm.systems and "父块完整上下文" in llm.systems[0]
    citation = result["citations"][0]
    assert citation["chunk_id"] == "c1"
    assert citation["page"] == 3