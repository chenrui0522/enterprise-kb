"""Aug-2026 correct-ledger gate (optional local paths / env).

Set:
  ATT_SYSTEM_XLSX  — system formal/preview export
  ATT_CORRECT_XLSX — 正确表 (default Desktop jm.xlsx)
Then:
  uv run pytest tests/test_correct_ledger_gate.py -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.attendance_summary.compare_ledger import compare_files, summarize

DEFAULT_CORRECT = Path(
    r"c:\Users\chenr\Desktop\奥特莱多智能体项目资料汇总‘\AI考勤统计\26年8月太原考勤汇总表jm.xlsx"
)
# Prefer fresh smoke formal, then Downloads d27 baseline
CANDIDATES = [
    Path(os.environ["ATT_SYSTEM_XLSX"]) if os.environ.get("ATT_SYSTEM_XLSX") else None,
    Path(r"c:\Users\chenr\AppData\Local\Temp\recovery\aug2026_smoke2\formal.xlsx"),
    Path(r"c:\Users\chenr\AppData\Local\Temp\recovery\aug2026_smoke2\preview.xlsx"),
]


def _system_path() -> Path | None:
    for p in CANDIDATES:
        if p and p.is_file():
            return p
    return None


@pytest.mark.skipif(
    _system_path() is None or not DEFAULT_CORRECT.is_file(),
    reason="system export or correct ledger missing",
)
def test_correct_ledger_non_exempt_gate() -> None:
    """Gate: non-exempt key diffs must be zero (only registered exemptions remain)."""
    system = _system_path()
    assert system is not None
    result = compare_files(system, DEFAULT_CORRECT)
    summary = summarize(result)
    assert summary["non_exempt_diffs"] == 0, summary
