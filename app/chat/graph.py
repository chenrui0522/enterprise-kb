from __future__ import annotations

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.chat.state import ChatState
from app.core.logging import get_logger
from app.providers.base import LLMProvider
from app.retrieval.service import SearchService

logger = get_logger("chat.graph")

GREETINGS = {"你好", "您好", "hi", "hello", "嗨", "谢谢", "感谢", "再见", "拜拜"}
GREETING_REPLIES = {
    "你好": "你好！我是企业知识库助手，可以问我产品手册、制度文档里的问题。",
    "您好": "您好！我是企业知识库助手，可以问我产品手册、制度文档里的问题。",
    "hi": "Hello! I can answer questions based on your knowledge base documents.",
    "hello": "Hello! I can answer questions based on your knowledge base documents.",
    "嗨": "你好！有什么可以帮你的吗？",
    "谢谢": "不客气，有问题随时问我。",
    "感谢": "不客气，有问题随时问我。",
    "再见": "再见，有需要再来找我。",
    "拜拜": "再见，有需要再来找我。",
}

REWRITE_SYSTEM = """你是企业知识库的查询改写器。用户会在多轮对话中提问。
结合最近几轮对话，把用户最新问题改写成一个**可独立用于文档检索**的问题；保留型号、编号等专有名词；如果问题本身已经完整独立，则原样返回。
只输出 JSON：{"rewritten_query": "改写后的问题"}。"""

JUDGE_SYSTEM = """判断用户最新问题是否需要查询企业文档知识库。
规则：
1. 寒暄、感谢、闲聊或仅围绕上一轮答案追问细节，且不引入文档新信息 → need_retrieval=false。
2. 其余需要查阅文档内容的问题 → need_retrieval=true。
只输出 JSON：{"need_retrieval": true/false, "reason": "一句话理由"}。"""

GENERATE_SYSTEM_TEMPLATE = """你是企业知识库问答助手。请严格依据下方【参考资料】回答用户问题：
- 只使用参考资料里出现的事实；参考资料没有的信息，不要编造。
- 每条关键论断后使用 [序号] 标注来源（如 [1][2]）。
- 如果参考资料不足以回答，明确说“当前知识库内容不足以可靠回答这个问题”，并建议补充文档或换一种问法，不要猜测。

【参考资料】
{references}"""

REFUSAL_ANSWER = (
    "抱歉，当前知识库中没有找到与这个问题相关的内容。"
    "你可以补充上传相关文档，或换一种问法再试一次。"
)

DIRECT_ANSWER_SYSTEM = """你是企业知识库助手。用户的问题不涉及文档检索。
请简洁友好地回答；如果问题超出了常识范围，请说明无法回答。不要编造文档内容。"""


def _normalize(text: str) -> str:
    return text.strip().lower().rstrip("?？")


def _last_exchanges(history: list[dict], turns: int) -> list[dict]:
    # Keep at most `turns` rounds (user+assistant pairs) for context windows.
    tail = history[-turns * 2 :] if turns * 2 < len(history) else history
    return tail


class ChatGraph:
    def __init__(
        self,
        llm: LLMProvider,
        search_service: SearchService,
        history_turns: int = 5,
        checkpointer=None,
    ) -> None:
        self._llm = llm
        self._search_service = search_service
        self._history_turns = history_turns
        self._graph = self._build(checkpointer=checkpointer)

    def _build(self, checkpointer=None):
        builder = StateGraph(ChatState)
        builder.add_node("rewrite", self._rewrite)
        builder.add_node("need_retrieval", self._need_retrieval)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("direct_answer", self._direct_answer)
        builder.add_node("generate", self._generate)
        builder.add_edge(START, "rewrite")
        builder.add_edge("rewrite", "need_retrieval")
        builder.add_conditional_edges(
            "need_retrieval",
            lambda state: "retrieve" if state["need_retrieval"] else "direct_answer",
            ["retrieve", "direct_answer"],
        )
        builder.add_edge("retrieve", "generate")
        builder.add_edge("direct_answer", END)
        builder.add_edge("generate", END)
        return builder.compile(checkpointer=checkpointer)

    @property
    def graph(self):
        return self._graph

    async def _rewrite(self, state: ChatState) -> dict:
        question = state["user_question"]
        normalized = _normalize(question)
        if normalized in {item.strip().lower() for item in GREETINGS}:
            return {"rewritten_query": question}
        history = _last_exchanges(state["history"], self._history_turns)
        if not history:
            return {"rewritten_query": question}
        transcript = "\n".join(
            f"{'用户' if message['role'] == 'user' else '助手'}: {message['content']}"
            for message in history[-6:]
        )
        payload = await self._llm.complete_json(
            system=REWRITE_SYSTEM,
            user=f"【最近对话】\n{transcript}\n\n【用户最新问题】\n{question}",
            temperature=0.1,
        )
        rewritten = str(payload.get("rewritten_query") or question).strip()
        return {"rewritten_query": rewritten or question}

    async def _need_retrieval(self, state: ChatState) -> dict:
        question = state["user_question"]
        normalized = _normalize(question)
        if normalized in {item.strip().lower() for item in GREETINGS}:
            return {"need_retrieval": False}
        history = _last_exchanges(state["history"], self._history_turns)
        transcript = "\n".join(
            f"{'用户' if message['role'] == 'user' else '助手'}: {message['content']}"
            for message in history[-6:]
        )
        payload = await self._llm.complete_json(
            system=JUDGE_SYSTEM,
            user=f"【最近对话】\n{transcript}\n\n【用户最新问题】\n{question}",
            temperature=0.0,
        )
        return {"need_retrieval": bool(payload.get("need_retrieval", True))}

    async def _retrieve(self, state: ChatState) -> dict:
        query = state.get("rewritten_query") or state["user_question"]
        hits = await self._search_service.search(query, state["tenant_id"])
        return {"hits": [hit.model_dump() for hit in hits]}

    async def _direct_answer(self, state: ChatState) -> dict:
        question = state["user_question"]
        normalized = _normalize(question)
        direct_reply = next((reply for key, reply in GREETING_REPLIES.items() if normalized == key), None)
        if direct_reply is not None:
            content = direct_reply
        else:
            previous = next(
                (message for message in reversed(state["history"]) if message["role"] == "assistant"),
                None,
            )
            context = f"上一轮回答：{previous['content']}\n\n" if previous else ""
            content = await self._llm.complete(system=DIRECT_ANSWER_SYSTEM, user=f"{context}{question}")
        return {
            "answer": content,
            "citations": [],
            "refused": False,
        }

    async def _generate(self, state: ChatState) -> dict:
        writer = get_stream_writer()
        hits = state.get("hits", [])
        if not hits:
            writer({"type": "token", "content": REFUSAL_ANSWER})
            return {
                "answer": REFUSAL_ANSWER,
                "citations": [],
                "refused": True,
                "refusal_reason": "no_relevant_content",
            }

        references = []
        citations = []
        for index, hit in enumerate(hits, start=1):
            references.append(
                f"[{index}]《{hit['title']}》第{hit['page']}页"
                + (f"（{hit['section']}）" if hit.get("section") else "")
                + f"：{hit['text']}"
            )
            citations.append(
                {
                    "chunk_id": hit["chunk_id"],
                    "doc_id": hit["doc_id"],
                    "document_title": hit["title"],
                    "page": hit["page"],
                    "section": hit.get("section") or None,
                }
            )
        system = GENERATE_SYSTEM_TEMPLATE.format(references="\n".join(references))

        full_text: list[str] = []
        try:
            async for delta in self._llm.stream(system=system, user=state["user_question"]):
                full_text.append(delta)
                writer({"type": "token", "content": delta})
        except Exception as exc:
            logger.exception("Generation stream failed")
            writer({"type": "error", "detail": f"生成失败：{exc}"})
            raise

        content = "".join(full_text)
        return {
            "answer": content,
            "citations": citations,
            "refused": False,
        }
