"""M3 turn routing: explicit tool > strong rules > weak clarify > none (RAG)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chat.tools.registry import TOOL_LEAVE_LEDGER, TOOL_STAFFING, ensure_tool_allowed
from app.identity.feature_gates import can_use_leave_ledger, can_use_staffing
from app.identity.principal import Principal

_STRONG_KW = re.compile(
    r"(人员投入|项目日报|在场|人天|出勤|导入日报|统计.*(人|天)|有谁|去了几天)",
    re.I,
)
_DAILY_NAME = re.compile(r"(项目日报|日报|staffing|attendance)", re.I)
_DAILY_FILE = re.compile(r"\.(xlsx?|pdf)$", re.I)

_LEAVE_KW = re.compile(
    r"(调休台账|调休|台账|出差|加班|请假|打卡|对账)",
    re.I,
)
_LEAVE_NAME = re.compile(r"(出差|加班|请假|打卡|调休|台账)", re.I)
_LEAVE_FILE = re.compile(r"\.xlsx?$", re.I)

_SCORE_RANK = {"none": 0, "weak": 1, "strong": 2}


@dataclass(frozen=True)
class RouteDecision:
    kind: str  # staffing | leave_ledger | clarify | conflict_clarify | none
    tool_id: str | None = None
    reason: str = ""


def _has_staffing_perm(principal: Principal) -> bool:
    return can_use_staffing(principal, write=None)


def _has_leave_perm(principal: Principal) -> bool:
    return can_use_leave_ledger(principal, write=None)


def score_staffing_match(*, message: str, filename: str | None) -> str:
    """Return strong | weak | none for staffing auto-trigger."""
    text = (message or "").strip()
    name = filename or ""
    has_daily = bool(name and _DAILY_FILE.search(name))
    strong_text = bool(_STRONG_KW.search(text))
    daily_name = bool(name and _DAILY_NAME.search(name))

    if has_daily and (strong_text or daily_name):
        return "strong"
    if has_daily or strong_text:
        return "weak"
    return "none"


def score_leave_ledger_match(*, message: str, filename: str | None) -> str:
    """Return strong | weak | none for leave-ledger auto-trigger."""
    text = (message or "").strip()
    name = filename or ""
    has_xlsx = bool(name and _LEAVE_FILE.search(name))
    strong_text = bool(_LEAVE_KW.search(text))
    leave_name = bool(name and _LEAVE_NAME.search(name))

    if has_xlsx and (strong_text or leave_name):
        return "strong"
    if has_xlsx or strong_text:
        return "weak"
    return "none"


def route_turn(
    principal: Principal,
    *,
    active_tool: str | None,
    message: str,
    filename: str | None = None,
) -> RouteDecision:
    """Decide how to handle this chat turn before RAG."""
    if active_tool:
        ensure_tool_allowed(principal, active_tool)
        if active_tool == TOOL_STAFFING:
            return RouteDecision(kind="staffing", tool_id=TOOL_STAFFING, reason="explicit")
        if active_tool == TOOL_LEAVE_LEDGER:
            return RouteDecision(
                kind="leave_ledger", tool_id=TOOL_LEAVE_LEDGER, reason="explicit"
            )
        return RouteDecision(kind="none", reason="unsupported_explicit")

    staffing_score = (
        score_staffing_match(message=message, filename=filename)
        if _has_staffing_perm(principal)
        else "none"
    )
    leave_score = (
        score_leave_ledger_match(message=message, filename=filename)
        if _has_leave_perm(principal)
        else "none"
    )

    s_rank = _SCORE_RANK[staffing_score]
    l_rank = _SCORE_RANK[leave_score]

    if s_rank and l_rank:
        if s_rank == l_rank:
            return RouteDecision(
                kind="conflict_clarify",
                tool_id=None,
                reason="staffing_leave_tie",
            )
        if s_rank > l_rank:
            if staffing_score == "strong":
                return RouteDecision(
                    kind="staffing", tool_id=TOOL_STAFFING, reason="strong_rules"
                )
            return RouteDecision(
                kind="clarify", tool_id=TOOL_STAFFING, reason="weak_rules"
            )
        if leave_score == "strong":
            return RouteDecision(
                kind="leave_ledger", tool_id=TOOL_LEAVE_LEDGER, reason="strong_rules"
            )
        return RouteDecision(
            kind="clarify", tool_id=TOOL_LEAVE_LEDGER, reason="weak_rules"
        )

    if leave_score == "strong":
        return RouteDecision(
            kind="leave_ledger", tool_id=TOOL_LEAVE_LEDGER, reason="strong_rules"
        )
    if staffing_score == "strong":
        return RouteDecision(kind="staffing", tool_id=TOOL_STAFFING, reason="strong_rules")
    if leave_score == "weak":
        return RouteDecision(
            kind="clarify", tool_id=TOOL_LEAVE_LEDGER, reason="weak_rules"
        )
    if staffing_score == "weak":
        return RouteDecision(kind="clarify", tool_id=TOOL_STAFFING, reason="weak_rules")

    if not _has_staffing_perm(principal) and not _has_leave_perm(principal):
        return RouteDecision(kind="none", reason="no_tool_perm")
    return RouteDecision(kind="none", reason="no_match")


def user_affirms_staffing(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"^(人员投入|要人员投入|用人员投入|确认人员投入)", text))


def user_declines_staffing(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"(只要讲解|不要人员投入|只讲解|讲解表格)", text))


def user_affirms_leave(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"^(调休台账|要调休台账|用调休台账|确认调休台账|调休)", text))


def user_declines_leave(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"(只要讲解|不要调休|只要讲解表格|讲解表格)", text))
