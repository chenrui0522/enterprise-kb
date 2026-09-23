"""M3 turn routing: explicit tool > strong rules > weak clarify > none (RAG)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chat.tools.registry import TOOL_STAFFING, ensure_tool_allowed
from app.identity.constants import PERM_STAFFING_READ, PERM_STAFFING_WRITE
from app.identity.principal import Principal

_STRONG_KW = re.compile(
    r"(人员投入|项目日报|在场|人天|出勤|导入日报|统计.*(人|天)|有谁|去了几天)",
    re.I,
)
_DAILY_NAME = re.compile(r"(项目日报|日报|staffing|attendance)", re.I)
_XLSX = re.compile(r"\.xlsx?$", re.I)


@dataclass(frozen=True)
class RouteDecision:
    kind: str  # staffing | clarify | none
    tool_id: str | None = None
    reason: str = ""


def _has_staffing_perm(principal: Principal) -> bool:
    perms = set(principal.permissions or ())
    return bool(perms & {PERM_STAFFING_READ, PERM_STAFFING_WRITE})


def score_staffing_match(*, message: str, filename: str | None) -> str:
    """Return strong | weak | none for staffing auto-trigger."""
    text = (message or "").strip()
    name = filename or ""
    has_xlsx = bool(name and _XLSX.search(name))
    strong_text = bool(_STRONG_KW.search(text))
    daily_name = bool(name and _DAILY_NAME.search(name))

    if has_xlsx and (strong_text or daily_name):
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
        return RouteDecision(kind="none", reason="unsupported_explicit")

    if not _has_staffing_perm(principal):
        return RouteDecision(kind="none", reason="no_staffing_perm")

    score = score_staffing_match(message=message, filename=filename)
    if score == "strong":
        return RouteDecision(kind="staffing", tool_id=TOOL_STAFFING, reason="strong_rules")
    if score == "weak":
        return RouteDecision(kind="clarify", tool_id=TOOL_STAFFING, reason="weak_rules")
    return RouteDecision(kind="none", reason="no_match")


def user_affirms_staffing(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"^(人员投入|要人员投入|用人员投入|确认人员投入)", text))


def user_declines_staffing(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.search(r"(只要讲解|不要人员投入|只讲解|讲解表格)", text))
