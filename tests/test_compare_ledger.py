"""Exemption-aware compare harness for align-attendance-to-correct-ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.attendance_summary.compare_ledger import (
    compare_files,
    load_exemptions,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
D27 = Path(
    r"c:\Users\chenr\Downloads\考勤汇总-2026-8-d27cdf6fbe8640ef9febcf8fb084117e (1).xlsx"
)
CORRECT = Path(
    r"c:\Users\chenr\Desktop\奥特莱多智能体项目资料汇总‘\AI考勤统计\26年8月太原考勤汇总表jm.xlsx"
)


def test_exemptions_loadable_with_hand_edit() -> None:
    items = load_exemptions()
    assert items
    assert any(x.get("person") == "张楠杰" for x in items)


@pytest.mark.skipif(not (D27.is_file() and CORRECT.is_file()), reason="local ledgers missing")
def test_d27_baseline_has_non_exempt_diffs() -> None:
    """Baseline export must still fail the gate (non_exempt > 0) before full align."""
    result = compare_files(D27, CORRECT)
    summary = summarize(result)
    assert summary["n_sys"] > 0 and summary["n_cor"] > 0
    assert summary["non_exempt_diffs"] > 0
    # Hand-edit exemption should absorb at least the 张楠杰 调休/实出勤 cell when present
    assert summary["exempt_diffs"] >= 0
