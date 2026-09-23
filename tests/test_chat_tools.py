"""Chat tool registry and M3 routing."""

from __future__ import annotations

import pytest

from app.chat.tools.registry import (
    TOOL_STAFFING,
    ensure_tool_allowed,
    list_tools_for_principal,
)
from app.chat.tools.router import route_turn, score_staffing_match
from app.core.errors import AppError
from app.identity.constants import PERM_CHAT_USE, PERM_STAFFING_READ, PERM_STAFFING_WRITE
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
    )


def test_list_tools_filters_by_permission() -> None:
    assert list_tools_for_principal(_principal(PERM_CHAT_USE)) == []
    tools = list_tools_for_principal(_principal(PERM_CHAT_USE, PERM_STAFFING_READ))
    assert any(t["id"] == TOOL_STAFFING for t in tools)


def test_ensure_tool_allowed_denies_without_staffing() -> None:
    with pytest.raises(AppError) as ei:
        ensure_tool_allowed(_principal(PERM_CHAT_USE), TOOL_STAFFING)
    assert ei.value.status_code == 403


def test_score_strong_weak_none() -> None:
    assert (
        score_staffing_match(message="帮我统计在场人天", filename="2515项目日报.xlsx")
        == "strong"
    )
    assert score_staffing_match(message="看看这个表", filename="data.xlsx") == "weak"
    assert score_staffing_match(message="打印机保修多久", filename=None) == "none"


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
