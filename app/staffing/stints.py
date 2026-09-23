"""Derive continuous work stints from on-site calendar dates."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_stints(dates: list[str]) -> list[dict[str, Any]]:
    """Split ISO date strings into contiguous calendar runs.

    Adjacent days (diff == 1) stay in one stint; a gap of ≥1 missing calendar
    day opens a new stint. Each stint: index (1-based), entry_date, exit_date, days.
    """
    if not dates:
        return []
    unique = sorted({d for d in dates if d})
    if not unique:
        return []

    parsed = [date.fromisoformat(d) for d in unique]
    stints: list[dict[str, Any]] = []
    run_start = parsed[0]
    run_end = parsed[0]

    for current in parsed[1:]:
        if current - run_end == timedelta(days=1):
            run_end = current
            continue
        stints.append(_stint(len(stints) + 1, run_start, run_end))
        run_start = current
        run_end = current

    stints.append(_stint(len(stints) + 1, run_start, run_end))
    return stints


def _stint(index: int, start: date, end: date) -> dict[str, Any]:
    return {
        "index": index,
        "entry_date": start.isoformat(),
        "exit_date": end.isoformat(),
        "days": (end - start).days + 1,
    }


def format_stints_compact(stints: list[dict[str, Any]]) -> str:
    """Compact display: ``1: 01-11~01-13; 2: 03-09~03-11``."""
    parts: list[str] = []
    for s in stints:
        entry = _mmdd(s.get("entry_date") or "")
        exit_ = _mmdd(s.get("exit_date") or "")
        parts.append(f"{s.get('index')}: {entry}~{exit_}")
    return "; ".join(parts)


def format_stints_summary(stints: list[dict[str, Any]]) -> str:
    """Readable summary: ``第1次 2026-01-11入→2026-01-13出(3天); …``."""
    parts: list[str] = []
    for s in stints:
        parts.append(
            f"第{s.get('index')}次 {s.get('entry_date')}入→{s.get('exit_date')}出"
            f"（{s.get('days')}天）"
        )
    return "；".join(parts)


def _mmdd(iso: str) -> str:
    if len(iso) >= 10:
        return f"{iso[5:7]}-{iso[8:10]}"
    return iso
