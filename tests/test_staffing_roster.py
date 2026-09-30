"""Unit tests for roster name correction."""

from __future__ import annotations

from app.staffing.roster import RosterEntry, correct_names_against_roster


def _book(*names: str) -> dict[str, RosterEntry]:
    return {
        n: RosterEntry(name=n, department="测试部", title="工程师") for n in names
    }


def test_exact_hit_keeps_name() -> None:
    rows = [{"work_date": "2026-01-01", "person_name": "王亮", "person_kind": "internal_formal"}]
    out, warnings = correct_names_against_roster(rows, roster=_book("王亮", "史承志"))
    assert out[0]["person_name"] == "王亮"
    assert warnings == []


def test_unique_prefix_auto_corrects() -> None:
    rows = [
        {"work_date": "2026-01-01", "person_name": "豆子", "person_kind": "internal_formal"},
        {"work_date": "2026-01-01", "person_name": "豆子度", "person_kind": "internal_formal"},
    ]
    out, warnings = correct_names_against_roster(rows, roster=_book("豆子度", "王亮"))
    assert {r["person_name"] for r in out} == {"豆子度"}
    assert any(w["code"] == "roster_name_corrected" for w in warnings)
    assert warnings[0]["detail"]["from_name"] == "豆子"
    assert warnings[0]["detail"]["to_name"] == "豆子度"


def test_ambiguous_prefix_unresolved() -> None:
    rows = [{"work_date": "2026-01-01", "person_name": "张", "person_kind": "internal_formal"}]
    out, warnings = correct_names_against_roster(
        rows, roster=_book("张三", "张伟", "王亮")
    )
    assert out[0]["person_name"] == "张"
    assert len(warnings) == 1
    assert warnings[0]["code"] == "roster_name_unresolved"
    assert set(warnings[0]["detail"]["candidates"]) == {"张三", "张伟"}


def test_unknown_name_unresolved() -> None:
    rows = [{"work_date": "2026-01-01", "person_name": "某某某", "person_kind": "internal_contract"}]
    out, warnings = correct_names_against_roster(rows, roster=_book("王亮"))
    assert out[0]["person_name"] == "某某某"
    assert warnings[0]["code"] == "roster_name_unresolved"
    assert warnings[0]["detail"]["candidates"] == []


def test_empty_roster_unavailable() -> None:
    rows = [{"work_date": "2026-01-01", "person_name": "王亮", "person_kind": "internal_formal"}]
    out, warnings = correct_names_against_roster(rows, roster={})
    assert out[0]["person_name"] == "王亮"
    assert warnings[0]["code"] == "roster_unavailable"
