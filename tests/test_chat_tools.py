"""Chat tool registry and M3 routing."""

from __future__ import annotations

import pytest

from app.chat.tools.registry import (
    TOOL_LEAVE_LEDGER,
    TOOL_STAFFING,
    ensure_tool_allowed,
    list_tools_for_principal,
)
from app.chat.tools.router import (
    route_turn,
    score_leave_ledger_match,
    score_staffing_match,
)
from app.core.errors import AppError
from app.identity.constants import (
    PERM_CHAT_USE,
    PERM_LEAVE_LEDGER_READ,
    PERM_LEAVE_LEDGER_WRITE,
    PERM_STAFFING_READ,
    PERM_STAFFING_WRITE,
)
from app.identity.principal import Principal


def _principal(*perms: str) -> Principal:
    return Principal(
        user_id="u1",
        tenant_id="autley",
        username="u",
        display_name="u",
        site="taiyuan",
        clearance="general",
        permissions=tuple(perms),
        staffing_org_ok=True,
        leave_ledger_org_ok=True,
    )


def test_list_tools_filters_by_permission() -> None:
    assert list_tools_for_principal(_principal(PERM_CHAT_USE)) == []
    tools = list_tools_for_principal(_principal(PERM_CHAT_USE, PERM_STAFFING_READ))
    assert any(t["id"] == TOOL_STAFFING for t in tools)
    assert not any(t["id"] == TOOL_LEAVE_LEDGER for t in tools)
    leave_tools = list_tools_for_principal(
        _principal(PERM_CHAT_USE, PERM_LEAVE_LEDGER_READ)
    )
    assert any(t["id"] == TOOL_LEAVE_LEDGER for t in leave_tools)
    assert not any(t["id"] == TOOL_STAFFING for t in leave_tools)
    both = list_tools_for_principal(
        _principal(PERM_CHAT_USE, PERM_STAFFING_READ, PERM_LEAVE_LEDGER_WRITE)
    )
    ids = {t["id"] for t in both}
    assert TOOL_STAFFING in ids and TOOL_LEAVE_LEDGER in ids


def test_ensure_tool_allowed_denies_without_staffing() -> None:
    with pytest.raises(AppError) as ei:
        ensure_tool_allowed(_principal(PERM_CHAT_USE), TOOL_STAFFING)
    assert ei.value.status_code == 403


def test_ensure_tool_allowed_denies_without_leave() -> None:
    with pytest.raises(AppError) as ei:
        ensure_tool_allowed(_principal(PERM_CHAT_USE), TOOL_LEAVE_LEDGER)
    assert ei.value.status_code == 403


def test_ensure_tool_allowed_denies_wrong_org() -> None:
    p = Principal(
        user_id="u1",
        tenant_id="autley",
        username="u",
        display_name="u",
        site="taiyuan",
        clearance="general",
        permissions=(PERM_CHAT_USE, PERM_STAFFING_WRITE, PERM_LEAVE_LEDGER_WRITE),
        staffing_org_ok=False,
        leave_ledger_org_ok=False,
    )
    with pytest.raises(AppError) as ei:
        ensure_tool_allowed(p, TOOL_STAFFING)
    assert ei.value.status_code == 403
    assert list_tools_for_principal(p) == []


def test_score_strong_weak_none() -> None:
    assert (
        score_staffing_match(message="帮我统计在场人天", filename="2515项目日报.xlsx")
        == "strong"
    )
    assert score_staffing_match(message="看看这个表", filename="data.xlsx") == "weak"
    assert score_staffing_match(message="打印机保修多久", filename=None) == "none"
    assert score_staffing_match(message="帮我统计在场人天", filename="日报.pdf") == "strong"
    assert score_staffing_match(message="看看这个", filename="report.pdf") == "weak"


def test_score_leave_ledger_strong_weak_none() -> None:
    assert (
        score_leave_ledger_match(message="做调休台账", filename="出差申请.xlsx")
        == "strong"
    )
    assert (
        score_leave_ledger_match(message="看看这个表", filename="加班申请.xlsx")
        == "strong"
    )
    assert score_leave_ledger_match(message="看看这个表", filename="data.xlsx") == "weak"
    assert score_leave_ledger_match(message="打印机保修多久", filename=None) == "none"
    assert score_leave_ledger_match(message="要做调休", filename=None) == "weak"


def test_route_explicit_and_rules() -> None:
    p = _principal(PERM_STAFFING_READ, PERM_STAFFING_WRITE)
    d = route_turn(p, active_tool=TOOL_STAFFING, message="你好", filename=None)
    assert d.kind == "staffing" and d.reason == "explicit"
    d2 = route_turn(
        p, active_tool=None, message="导入项目日报", filename="项目日报1.xlsx"
    )
    assert d2.kind == "staffing"
    d3 = route_turn(p, active_tool=None, message="看下这表", filename="a.xlsx")
    assert d3.kind == "clarify"
    d4 = route_turn(
        _principal(PERM_CHAT_USE),
        active_tool=None,
        message="导入项目日报",
        filename="项目日报1.xlsx",
    )
    assert d4.kind == "none"


def test_route_leave_ledger_explicit_strong_weak() -> None:
    p = _principal(PERM_LEAVE_LEDGER_READ, PERM_LEAVE_LEDGER_WRITE)
    d = route_turn(p, active_tool=TOOL_LEAVE_LEDGER, message="你好", filename=None)
    assert d.kind == "leave_ledger" and d.reason == "explicit"
    d2 = route_turn(
        p, active_tool=None, message="做调休台账", filename="出差申请.xlsx"
    )
    assert d2.kind == "leave_ledger" and d2.reason == "strong_rules"
    d3 = route_turn(p, active_tool=None, message="看下这表", filename="a.xlsx")
    assert d3.kind == "clarify" and d3.tool_id == TOOL_LEAVE_LEDGER
    d4 = route_turn(
        _principal(PERM_CHAT_USE),
        active_tool=None,
        message="做调休台账",
        filename="出差申请.xlsx",
    )
    assert d4.kind == "none"


def test_route_staffing_leave_conflict_and_stronger_wins() -> None:
    both = _principal(
        PERM_STAFFING_READ,
        PERM_STAFFING_WRITE,
        PERM_LEAVE_LEDGER_READ,
        PERM_LEAVE_LEDGER_WRITE,
    )
    # Tied weak → conflict clarify
    tied = route_turn(both, active_tool=None, message="看下这表", filename="a.xlsx")
    assert tied.kind == "conflict_clarify"
    # Staffing strong beats leave weak
    staff = route_turn(
        both, active_tool=None, message="导入项目日报", filename="项目日报.xlsx"
    )
    assert staff.kind == "staffing"
    # Leave strong beats staffing weak (generic xlsx + leave keywords)
    leave = route_turn(
        both, active_tool=None, message="做调休台账", filename="出差申请.xlsx"
    )
    assert leave.kind == "leave_ledger"
    # Explicit leave wins even if staffing keywords present
    explicit = route_turn(
        both,
        active_tool=TOOL_LEAVE_LEDGER,
        message="导入项目日报",
        filename="项目日报.xlsx",
    )
    assert explicit.kind == "leave_ledger" and explicit.reason == "explicit"
