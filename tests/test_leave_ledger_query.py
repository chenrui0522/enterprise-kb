"""Unit tests for leave-ledger chat query helpers."""

from __future__ import annotations

from app.chat.tools.leave_ledger_query import (
    answer_leave_query,
    format_person_answer,
    match_person_row,
)


def _rows() -> list[dict]:
    return [
        {
            "person_name": "张三",
            "travel_comp_days": 2,
            "ot_comp_days": 1,
            "total_comp_days": 3,
            "used_comp_days": 1,
            "remaining_comp_days": 2,
            "remark": "项目出差30天→2天",
            "ot_days": [{"date": "2026-06-19", "credit": 1.0, "holiday": True}],
        },
        {
            "person_name": "张三丰",
            "travel_comp_days": 0,
            "ot_comp_days": 1,
            "total_comp_days": 1,
            "used_comp_days": 0,
            "remaining_comp_days": 1,
            "remark": "",
            "ot_days": [{"date": "2026-05-01", "credit": 1.0}],
        },
    ]


def test_longest_name_match() -> None:
    row = match_person_row("张三丰剩余调休多少", _rows())
    assert isinstance(row, dict)
    assert row["person_name"] == "张三丰"


def test_missing_person() -> None:
    assert match_person_row("李四剩余几天", _rows()) is None


def test_format_remaining_field() -> None:
    text = format_person_answer("张三剩余调休", _rows()[0])
    assert "剩余调休 2 天" in text
    assert "出差可调休" not in text


def test_answer_summary() -> None:
    ans, _ = answer_leave_query(
        "多少人汇总",
        rows=_rows(),
        job_status="parsed",
        warning_count=3,
        open_blocking=1,
        totals={"total_comp_days": 4, "used_comp_days": 1, "remaining_comp_days": 3},
    )
    assert ans is not None
    assert "共 2 人" in ans
    assert "合计可调休 4 天" in ans


def test_answer_unknown_person() -> None:
    ans, _ = answer_leave_query(
        "王五出差可调休几天",
        rows=_rows(),
        job_status="parsed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert "未在当前台账结果中找到" in ans


def test_empty_rows() -> None:
    ans, _ = answer_leave_query(
        "张三剩余",
        rows=[],
        job_status="collecting",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert "尚无预览行" in ans


def test_presence_yes() -> None:
    ans, sticky = answer_leave_query(
        "这份台账有没有张三",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert ans.startswith("有。")
    assert "张三在当前台账中" in ans
    assert sticky == "张三"


def test_presence_no() -> None:
    ans, _ = answer_leave_query(
        "这份台账有没有陈锐",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert ans.startswith("没有。")
    assert "陈锐" in ans


def test_merge_help_when_confirmed() -> None:
    ans, _ = answer_leave_query(
        "结合上一版本的调休台账进行合并",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert "已确认" in ans
    assert "确认台账" in ans and "之前" in ans


def test_merge_help_where_is_prior_card() -> None:
    ans, _ = answer_leave_query(
        "上个月调休台账卡片在哪",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert "没有单独" in ans or "确认前" in ans
    assert "未在当前台账结果中找到对应人员" not in ans


def test_pronoun_ot_date_uses_last_person() -> None:
    ans, sticky = answer_leave_query(
        "他加班调休是哪一天",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
        last_person_name="张三",
    )
    assert ans is not None
    assert "2026-06-19" in ans
    assert sticky == "张三"


def test_ot_date_by_name() -> None:
    ans, sticky = answer_leave_query(
        "张三丰加班哪一天",
        rows=_rows(),
        job_status="confirmed",
        warning_count=0,
        open_blocking=0,
    )
    assert ans is not None
    assert "2026-05-01" in ans
    assert sticky == "张三丰"
