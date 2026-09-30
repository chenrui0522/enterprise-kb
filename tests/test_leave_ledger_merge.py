"""Segment merge for leave-ledger prior + current rows."""

from __future__ import annotations

from app.leave_ledger.merge import (
    filter_warnings_covered_by_prior,
    merge_ledger_rows,
    prior_ot_keys,
    synthesize_segments,
)


def test_travel_overlap_recomputes_30_day_credit() -> None:
    prior = [
        {
            "person_name": "甲",
            "center": "太原",
            "department": "项目一部",
            "travel_segments": [
                {
                    "system_start": "2026-01-01",
                    "system_end": "2026-01-20",
                    "actual_start": "2026-01-01",
                    "actual_end": "2026-01-20",
                    "credit": 0,
                }
            ],
            "ot_days": [],
            "leave_segments": [],
            "travel_comp_days": 0,
            "ot_comp_days": 0,
            "used_comp_days": 0,
        }
    ]
    current = [
        {
            "person_name": "甲",
            "center": "太原",
            "department": "项目一部",
            "travel_segments": [
                {
                    "system_start": "2026-01-15",
                    "system_end": "2026-02-10",
                    "actual_start": "2026-01-15",
                    "actual_end": "2026-02-10",
                    "credit": 0,
                }
            ],
            "ot_days": [],
            "leave_segments": [],
            "travel_comp_days": 0,
            "ot_comp_days": 0,
            "used_comp_days": 0,
        }
    ]
    merged = merge_ledger_rows(prior, current, merge_gap_days=1)
    assert len(merged) == 1
    assert merged[0]["travel_comp_days"] == 2.0  # 1/1-2/10 = 41 days
    assert len(merged[0]["travel_segments"]) == 1
    assert merged[0]["remaining_comp_days"] == 2.0


def test_ot_prior_wins_same_day() -> None:
    prior = [
        {
            "person_name": "乙",
            "ot_days": [{"date": "2026-01-05", "credit": 0.0, "holiday": False}],
            "travel_segments": [],
            "leave_segments": [],
        }
    ]
    current = [
        {
            "person_name": "乙",
            "ot_days": [{"date": "2026-01-05", "credit": 1.0, "holiday": False}],
            "travel_segments": [],
            "leave_segments": [],
        }
    ]
    merged = merge_ledger_rows(prior, current)
    assert merged[0]["ot_comp_days"] == 0.0
    assert merged[0]["ot_days"][0]["credit"] == 0.0


def test_leave_key_dedupe_prior_wins() -> None:
    prior = [
        {
            "person_name": "丙",
            "leave_segments": [
                {"start": "2026-02-01", "end": "2026-02-01", "used_days": 1.0}
            ],
            "travel_segments": [],
            "ot_days": [],
        }
    ]
    current = [
        {
            "person_name": "丙",
            "leave_segments": [
                {"start": "2026-02-01", "end": "2026-02-01", "used_days": 0.5},
                {"start": "2026-02-10", "end": "2026-02-10", "used_days": 1.0},
            ],
            "travel_segments": [],
            "ot_days": [{"date": "2026-01-01", "credit": 2.0}],
        }
    ]
    merged = merge_ledger_rows(prior, current)
    assert merged[0]["used_comp_days"] == 2.0  # 1.0 prior + 1.0 new
    assert len(merged[0]["leave_segments"]) == 2


def test_synthesize_missing_travel_segments() -> None:
    person = {
        "person_name": "丁",
        "system_travel_start": "2026-03-01",
        "system_travel_end": "2026-03-31",
        "actual_travel_start": "2026-03-01",
        "actual_travel_end": "2026-03-31",
        "travel_comp_days": 2,
    }
    syn = synthesize_segments(person)
    assert len(syn["travel_segments"]) == 1
    prior = [syn]
    current = [{"person_name": "丁", "travel_segments": [], "ot_days": [], "leave_segments": []}]
    merged = merge_ledger_rows(prior, current)
    assert merged[0]["travel_comp_days"] == 2.0


def test_filter_warnings_covered_by_prior() -> None:
    prior_rows = [
        {
            "person_name": "甲",
            "ot_days": [{"date": "2026-01-05", "credit": 1.0}],
        }
    ]
    warnings = [
        {
            "code": "ot_missing_punch",
            "blocking": True,
            "detail": {"person": "甲", "date": "2026-01-05"},
        },
        {
            "code": "ot_missing_punch",
            "blocking": True,
            "detail": {"person": "甲", "date": "2026-01-06"},
        },
    ]
    keys = prior_ot_keys(prior_rows)
    filtered = filter_warnings_covered_by_prior(warnings, keys)
    assert len(filtered) == 1
    assert filtered[0]["detail"]["date"] == "2026-01-06"
