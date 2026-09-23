"""Allowlisted chat tools and permission checks."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import AppError
from app.identity.constants import PERM_STAFFING_READ, PERM_STAFFING_WRITE
from app.identity.principal import Principal

TOOL_STAFFING = "staffing"

WEAK_CLARIFY_COPY = (
    "看到你发了表格或提到相关需求。是要做「人员投入」统计（导入项目日报、看谁在场几天），"
    "还是只要讲解表格内容？请回复「人员投入」或「只要讲解」。"
)


@dataclass(frozen=True)
class ChatTool:
    id: str
    label: str
    permissions: frozenset[str]


CHAT_TOOLS: tuple[ChatTool, ...] = (
    ChatTool(
        id=TOOL_STAFFING,
        label="人员投入",
        permissions=frozenset({PERM_STAFFING_READ, PERM_STAFFING_WRITE}),
    ),
)


def get_tool(tool_id: str) -> ChatTool | None:
    for tool in CHAT_TOOLS:
        if tool.id == tool_id:
            return tool
    return None


def list_tools_for_principal(principal: Principal) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    perms = set(principal.permissions or ())
    for tool in CHAT_TOOLS:
        if perms & tool.permissions:
            out.append({"id": tool.id, "label": tool.label})
    return out


def ensure_tool_allowed(principal: Principal, tool_id: str) -> ChatTool:
    tool = get_tool(tool_id)
    if tool is None:
        raise AppError("未知工具", status_code=404)
    if not (set(principal.permissions or ()) & tool.permissions):
        raise AppError("无权使用该工具", status_code=403)
    return tool
