"""Unit tests for conversation rule titles and polish sanitize."""

from __future__ import annotations

from app.chat.title import (
    DEFAULT_TITLE,
    TITLE_SOURCE_AUTO,
    TITLE_SOURCE_DEFAULT,
    TITLE_SOURCE_USER,
    apply_rule_title_if_default,
    derive_rule_title,
    sanitize_polished_title,
)
from app.models.entity import Conversation


def test_derive_rule_title_from_message() -> None:
    assert derive_rule_title("打印机保修期多久") == "打印机保修期多久"


def test_derive_rule_title_truncates() -> None:
    long = "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十"
    out = derive_rule_title(long)
    assert len(out) == 30
    assert out.startswith("一二三")


def test_derive_rule_title_collapses_whitespace() -> None:
    assert derive_rule_title("  报销   流程  \n如何  ") == "报销 流程 如何"


def test_derive_rule_title_from_filename() -> None:
    assert derive_rule_title("   ", "2515项目日报.xlsx") == "2515项目日报"


def test_derive_rule_title_empty_fallback() -> None:
    assert derive_rule_title("", None) == DEFAULT_TITLE
    assert derive_rule_title("  ", "") == DEFAULT_TITLE


def test_apply_rule_title_only_when_default() -> None:
    conv = Conversation(tenant_id="t", title=DEFAULT_TITLE, title_source=TITLE_SOURCE_DEFAULT)
    assert apply_rule_title_if_default(conv, message="保修期") == "保修期"
    assert conv.title_source == TITLE_SOURCE_AUTO

    assert apply_rule_title_if_default(conv, message="另一句") is None
    assert conv.title == "保修期"


def test_apply_rule_title_skips_user() -> None:
    conv = Conversation(tenant_id="t", title="我的会话", title_source=TITLE_SOURCE_USER)
    assert apply_rule_title_if_default(conv, message="保修期") is None
    assert conv.title == "我的会话"


def test_sanitize_polished_title() -> None:
    assert sanitize_polished_title('  "保修问答"  ') == "保修问答"
    assert sanitize_polished_title("") is None
    assert sanitize_polished_title(DEFAULT_TITLE) is None
    long = "一二三四五六七八九十一二三四五六七八九十多余"
    assert len(sanitize_polished_title(long) or "") == 20
