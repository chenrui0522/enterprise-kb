"""Allowlisted chat tools and permission checks."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import AppError
from app.identity.constants import (
    PERM_LEAVE_LEDGER_READ,
    PERM_LEAVE_LEDGER_WRITE,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
)
from app.identity.feature_gates import can_use_leave_ledger, can_use_staffing
from app.identity.principal import Principal

TOOL_STAFFING = "staffing"
TOOL_LEAVE_LEDGER = "leave_ledger"

WEAK_CLARIFY_COPY = (
    "看到你发了表格或提到相关需求。是要做「人员投入」统计（导入项目日报、看谁在场几天），"
    "还是只要讲解表格内容？请回复「人员投入」或「只要讲解」。"
)

LEAVE_WEAK_CLARIFY_COPY = (
    "看到你发了考勤类表格或提到相关需求。是要做「调休台账」（出差/加班/请假/打卡对账），"
    "还是只要讲解表格内容？请回复「调休台账」或「只要讲解」。"
)

TOOL_CONFLICT_CLARIFY_COPY = (
    "这份表格既像「人员投入」项目日报，也像「调休台账」考勤来源。"
    "请回复「人员投入」或「调休台账」以便继续。"
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
    ChatTool(
        id=TOOL_LEAVE_LEDGER,
        label="调休台账",
        permissions=frozenset({PERM_LEAVE_LEDGER_READ, PERM_LEAVE_LEDGER_WRITE}),
    ),
)


def get_tool(tool_id: str) -> ChatTool | None:
    for tool in CHAT_TOOLS:
        if tool.id == tool_id:
            return tool
    return None


def list_tools_for_principal(principal: Principal) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tool in CHAT_TOOLS:
        if tool.id == TOOL_STAFFING and can_use_staffing(principal, write=None):
            out.append({"id": tool.id, "label": tool.label})
        elif tool.id == TOOL_LEAVE_LEDGER and can_use_leave_ledger(principal, write=None):
            out.append({"id": tool.id, "label": tool.label})
    return out


def ensure_tool_allowed(principal: Principal, tool_id: str) -> ChatTool:
    tool = get_tool(tool_id)
    if tool is None:
        raise AppError("未知工具", status_code=404)
    if tool_id == TOOL_STAFFING:
        if not can_use_staffing(principal, write=None):
            raise AppError("无权使用该工具", status_code=403)
    elif tool_id == TOOL_LEAVE_LEDGER:
        if not can_use_leave_ledger(principal, write=None):
            raise AppError("无权使用该工具", status_code=403)
    else:
        raise AppError("无权使用该工具", status_code=403)
    return tool
