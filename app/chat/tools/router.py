"""M3 turn routing: explicit tool > sticky > strong exclusive > clarify > none (RAG)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chat.tools.registry import (
    TOOL_ATTENDANCE_SUMMARY,
    TOOL_LEAVE_LEDGER,
    TOOL_STAFFING,
    ensure_tool_allowed,
)
from app.identity.feature_gates import (
    can_use_attendance_summary,
    can_use_leave_ledger,
    can_use_staffing,
)
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

_LEAVE_EXCLUSIVE = re.compile(
    r"(调休台账|可调休|调休对账|要调休台账|用调休台账|确认调休台账)",
    re.I,
)
_ATTENDANCE_EXCLUSIVE = re.compile(
    r"(考勤汇总|太原考勤|花名册|实出勤|考勤汇总台账|要考勤汇总|用考勤汇总)",
    re.I,
)
_ATTENDANCE_NAME = re.compile(r"(花名册|考勤汇总|太原考勤)", re.I)
_LEDGER_SHARED_NAME = re.compile(r"(出差|加班|请假|打卡|调休|台账|花名册|考勤)", re.I)

_SCORE_RANK = {"none": 0, "weak": 1, "strong": 2}


@dataclass(frozen=True)
class RouteDecision:
    kind: str  # staffing | leave_ledger | attendance_summary | clarify | conflict_clarify | ledger_clarify | none
    tool_id: str | None = None
    reason: str = ""


def _has_staffing_perm(principal: Principal) -> bool:
    return can_use_staffing(principal, write=None)


def _has_leave_perm(principal: Principal) -> bool:
    return can_use_leave_ledger(principal, write=None)


def _has_attendance_perm(principal: Principal) -> bool:
    return can_use_attendance_summary(principal, write=None)


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


def score_attendance_summary_match(*, message: str, filename: str | None) -> str:
    """Return strong | weak | none for attendance-summary auto-trigger."""
    text = (message or "").strip()
    name = filename or ""
    has_xlsx = bool(name and _LEAVE_FILE.search(name))
    exclusive = bool(_ATTENDANCE_EXCLUSIVE.search(text))
    att_name = bool(name and _ATTENDANCE_NAME.search(name))
    shared_name = bool(name and _LEDGER_SHARED_NAME.search(name))
    shared_text = bool(_LEAVE_KW.search(text) or _ATTENDANCE_EXCLUSIVE.search(text))

    if exclusive or (has_xlsx and att_name):
        return "strong"
    if has_xlsx and (shared_name or shared_text or exclusive):
        return "strong" if exclusive or att_name else "weak"
    if has_xlsx or shared_text or exclusive:
        return "weak" if not exclusive else "strong"
    return "none"


def leave_exclusive_intent(message: str) -> bool:
    return bool(_LEAVE_EXCLUSIVE.search(message or ""))


def attendance_exclusive_intent(message: str) -> bool:
    return bool(_ATTENDANCE_EXCLUSIVE.search(message or ""))


def sticky_leave_tool_if_job(
    principal: Principal,
    *,
    tool_state: dict | None,
    active_tool: str | None,
) -> str | None:
    """If composer cleared sticky tool but a leave job is still bound, keep leave_ledger."""
    if active_tool:
        return active_tool
    if not _has_leave_perm(principal):
        return None
    leave_st = (tool_state or {}).get("leave_ledger") or {}
    if leave_st.get("job_id"):
        return TOOL_LEAVE_LEDGER
    return None


def sticky_attendance_tool_if_job(
    principal: Principal,
    *,
    tool_state: dict | None,
    active_tool: str | None,
) -> str | None:
    if active_tool:
        return active_tool
    if not _has_attendance_perm(principal):
        return None
    st = (tool_state or {}).get("attendance_summary") or {}
    if st.get("job_id"):
        return TOOL_ATTENDANCE_SUMMARY
    return None


def resolve_sticky_active_tool(
    principal: Principal,
    *,
    tool_state: dict | None,
    active_tool: str | None,
) -> tuple[str | None, str | None]:
    """Return (active_tool, dual_sticky_flag). dual_sticky_flag='dual' when both jobs bound."""
    if active_tool:
        return active_tool, None
    leave_id = ((tool_state or {}).get("leave_ledger") or {}).get("job_id")
    att_id = ((tool_state or {}).get("attendance_summary") or {}).get("job_id")
    leave_ok = bool(leave_id and _has_leave_perm(principal))
    att_ok = bool(att_id and _has_attendance_perm(principal))
    if leave_ok and att_ok:
        return None, "dual"
    if leave_ok:
        return TOOL_LEAVE_LEDGER, None
    if att_ok:
        return TOOL_ATTENDANCE_SUMMARY, None
    return None, None


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
        if active_tool == TOOL_ATTENDANCE_SUMMARY:
            return RouteDecision(
                kind="attendance_summary",
                tool_id=TOOL_ATTENDANCE_SUMMARY,
                reason="explicit",
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
    attendance_score = (
        score_attendance_summary_match(message=message, filename=filename)
        if _has_attendance_perm(principal)
        else "none"
    )

    s_rank = _SCORE_RANK[staffing_score]
    l_rank = _SCORE_RANK[leave_score]
    a_rank = _SCORE_RANK[attendance_score]

    leave_ex = leave_exclusive_intent(message) and _has_leave_perm(principal)
    att_ex = attendance_exclusive_intent(message) and _has_attendance_perm(principal)

    # Exclusive intents skip leave-vs-attendance clarify.
    if leave_ex and not att_ex:
        return RouteDecision(
            kind="leave_ledger", tool_id=TOOL_LEAVE_LEDGER, reason="strong_rules"
        )
    if att_ex and not leave_ex:
        return RouteDecision(
            kind="attendance_summary",
            tool_id=TOOL_ATTENDANCE_SUMMARY,
            reason="strong_rules",
        )

    # Both leave and attendance look relevant → always clarify when both permitted.
    if l_rank and a_rank and _has_leave_perm(principal) and _has_attendance_perm(principal):
        if s_rank and s_rank == max(l_rank, a_rank):
            return RouteDecision(
                kind="conflict_clarify",
                tool_id=None,
                reason="staffing_ledger_tie",
            )
        return RouteDecision(
            kind="ledger_clarify",
            tool_id=None,
            reason="leave_attendance_ambiguous",
        )

    # Staffing vs single ledger tool
    ledger_rank = max(l_rank, a_rank)
    ledger_kind = "leave_ledger" if l_rank >= a_rank else "attendance_summary"
    ledger_tool = TOOL_LEAVE_LEDGER if ledger_kind == "leave_ledger" else TOOL_ATTENDANCE_SUMMARY
    ledger_score = leave_score if ledger_kind == "leave_ledger" else attendance_score

    if s_rank and ledger_rank:
        if s_rank == ledger_rank:
            return RouteDecision(
                kind="conflict_clarify",
                tool_id=None,
                reason="staffing_leave_tie",
            )
        if s_rank > ledger_rank:
            if staffing_score == "strong":
                return RouteDecision(
                    kind="staffing", tool_id=TOOL_STAFFING, reason="strong_rules"
                )
            return RouteDecision(
                kind="clarify", tool_id=TOOL_STAFFING, reason="weak_rules"
            )
        if ledger_score == "strong":
            return RouteDecision(
                kind=ledger_kind, tool_id=ledger_tool, reason="strong_rules"
            )
        return RouteDecision(kind="clarify", tool_id=ledger_tool, reason="weak_rules")

    if ledger_score == "strong":
        return RouteDecision(kind=ledger_kind, tool_id=ledger_tool, reason="strong_rules")
    if staffing_score == "strong":
        return RouteDecision(kind="staffing", tool_id=TOOL_STAFFING, reason="strong_rules")
    if ledger_score == "weak":
        return RouteDecision(kind="clarify", tool_id=ledger_tool, reason="weak_rules")
    if staffing_score == "weak":
        return RouteDecision(kind="clarify", tool_id=TOOL_STAFFING, reason="weak_rules")

    if (
        not _has_staffing_perm(principal)
        and not _has_leave_perm(principal)
        and not _has_attendance_perm(principal)
    ):
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


def user_affirms_attendance(message: str) -> bool:
    text = (message or "").strip()
    return bool(
        re.search(
            r"^(考勤汇总台账|考勤汇总|要考勤汇总|用考勤汇总|确认考勤汇总)",
            text,
        )
    )


def user_declines_attendance(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"(只要讲解|不要考勤|只要讲解表格|讲解表格)", text))
