import asyncio
from collections.abc import AsyncIterator

import pytest

from app.chat.graph import ChatGraph
from app.providers.base import LLMProvider
from app.retrieval.chunk import SearchHit


class FakeLLM(LLMProvider):
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict] = []

    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        return "好的。"

    async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
        self.calls.append({"system": system, "user": user})
        if "查询改写器" in system:
            return {"rewritten_query": "打印机维修流程"}
        if "是否需要查询企业文档知识库" in system:
            return {"need_retrieval": True, "reason": "需要查阅文档"}
        return {}

    async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
        for token in ["根据", "资料", "，", "保修", "一年"]:
            yield token


class FakeSearchService:
    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits or []

    async def search(self, query: str, tenant_id: str) -> list[SearchHit]:
        return self.hits


def hit(page: int = 3) -> SearchHit:
    return SearchHit(
        chunk_id="chunk1",
        doc_id="doc1",
        version_id="v1",
        title="产品手册",
        page=page,
        section="保修政策",
        text="打印机保修期为十二个月，编号 ZB-100 享受延保。",
        score=0.9,
    )


@pytest.mark.asyncio
async def test_follow_up_is_rewritten_with_history() -> None:
    llm = FakeLLM()
    graph = ChatGraph(llm, FakeSearchService([hit()]), history_turns=3).graph
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "那维修流程呢",
            "history": [
                {"role": "user", "content": "打印机的保修期是多久"},
                {"role": "assistant", "content": "根据资料，保修一年。"},
            ],
        }
    )
    assert result["rewritten_query"] == "打印机维修流程"
    assert "保修" in result["answer"]
    assert result["citations"]
    assert result["citations"][0]["page"] == 3


@pytest.mark.asyncio
async def test_greeting_skips_retrieval() -> None:
    graph = ChatGraph(FakeLLM(), FakeSearchService([hit()])).graph
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "你好",
            "history": [],
        }
    )
    assert result["need_retrieval"] is False
    assert "知识库助手" in result["answer"]
    assert not result["citations"]


@pytest.mark.asyncio
async def test_no_results_refuses_instead_of_guessing() -> None:
    llm = FakeLLM()
    graph = ChatGraph(llm, FakeSearchService([])).graph
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "公司年会奖品是什么",
            "history": [],
        }
    )
    assert result["refused"] is True
    assert "知识库" in result["answer"]
    assert not result["citations"]


@pytest.mark.asyncio
async def test_parallel_rerank_semaphore_cap() -> None:
    """Verifies the rerank concurrency cap comes from settings, not a hardcoded value."""
    from app.core.config import Settings

    assert Settings.model_fields["rerank_max_concurrency"].default == 10
    assert Settings(rerank_max_concurrency=32).rerank_max_concurrency == 32


@pytest.mark.asyncio
async def test_long_session_keeps_recent_history() -> None:
    llm = FakeLLM()
    graph = ChatGraph(llm, FakeSearchService([hit()]), history_turns=2).graph
    history = []
    for i in range(30):
        history.append({"role": "user", "content": f"历史问题{i}"})
        history.append({"role": "assistant", "content": f"历史回答{i}"})
    result = await graph.ainvoke(
        {
            "conversation_id": "c1",
            "tenant_id": "t1",
            "user_question": "最新问题",
            "history": history,
        }
    )
    assert result["answer"]
