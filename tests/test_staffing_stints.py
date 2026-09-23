"""Unit tests for calendar-gap stint derivation."""

from __future__ import annotations

from app.staffing.stints import build_stints, format_stints_compact


def test_build_stints_empty() -> None:
    assert build_stints([]) == []
    assert build_stints([""]) == []


def test_build_stints_single_day() -> None:
    assert build_stints(["2026-01-11"]) == [
        {
            "index": 1,
            "entry_date": "2026-01-11",
            "exit_date": "2026-01-11",
            "days": 1,
        }
    ]


def test_build_stints_one_continuous_run() -> None:
    dates = ["2026-01-13", "2026-01-11", "2026-01-12", "2026-01-11"]
    assert build_stints(dates) == [
        {
            "index": 1,
            "entry_date": "2026-01-11",
            "exit_date": "2026-01-13",
            "days": 3,
        }
    ]


def test_build_stints_two_runs() -> None:
    dates = [
        "2026-01-11",
        "2026-01-12",
        "2026-01-13",
        "2026-03-09",
        "2026-03-10",
        "2026-03-11",
    ]
    assert build_stints(dates) == [
        {
            "index": 1,
            "entry_date": "2026-01-11",
            "exit_date": "2026-01-13",
            "days": 3,
        },
        {
            "index": 2,
            "entry_date": "2026-03-09",
            "exit_date": "2026-03-11",
            "days": 3,
        },
    ]


def test_build_stints_three_runs() -> None:
    dates = [
        "2026-01-01",
        "2026-02-01",
        "2026-02-02",
        "2026-04-10",
        "2026-04-11",
        "2026-04-12",
    ]
    stints = build_stints(dates)
    assert len(stints) == 3
    assert stints[0] == {
        "index": 1,
        "entry_date": "2026-01-01",
        "exit_date": "2026-01-01",
        "days": 1,
    }
    assert stints[1]["index"] == 2
    assert stints[1]["entry_date"] == "2026-02-01"
    assert stints[1]["exit_date"] == "2026-02-02"
    assert stints[1]["days"] == 2
    assert stints[2] == {
        "index": 3,
        "entry_date": "2026-04-10",
        "exit_date": "2026-04-12",
        "days": 3,
    }


def test_format_stints_compact() -> None:
    text = format_stints_compact(build_stints(["2026-01-11", "2026-01-12", "2026-03-09"]))
    assert text == "1: 01-11~01-12; 2: 03-09~03-09"


def test_format_stints_summary() -> None:
    from app.staffing.stints import format_stints_summary

    text = format_stints_summary(build_stints(["2026-01-11", "2026-01-12", "2026-03-09"]))
    assert "第1次 2026-01-11入→2026-01-12出（2天）" in text
    assert "第2次 2026-03-09入→2026-03-09出（1天）" in text
