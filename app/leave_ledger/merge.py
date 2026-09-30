"""Segment-level merge of prior confirmed ledger rows into current compute rows."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.leave_ledger.rules import _merge_project_segments


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # tolerate "YYYY-MM-DD(法定)"
    text = text.replace("(法定)", "").strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _travel_credit(days: int) -> float:
    return float((days // 30) * 2)


def synthesize_segments(person: dict[str, Any]) -> dict[str, Any]:
    """Fill missing segment lists from aggregate fields (older snapshots)."""
    out = dict(person)
    travel = list(out.get("travel_segments") or [])
    if not travel and (
        out.get("system_travel_start") or out.get("actual_travel_start")
    ):
        travel = [
            {
                "system_start": out.get("system_travel_start") or "",
                "system_end": out.get("system_travel_end") or "",
                "actual_start": out.get("actual_travel_start") or "",
                "actual_end": out.get("actual_travel_end") or "",
                "credit": out.get("travel_comp_days") or 0,
            }
        ]
    ot_days = list(out.get("ot_days") or [])
    if not ot_days and float(out.get("ot_comp_days") or 0) > 0:
        raw = (out.get("ot_dates") or "").split("、")
        first = (raw[0] or "").replace("(法定)", "").strip() if raw else ""
        if first:
            ot_days = [{"date": first, "credit": out.get("ot_comp_days") or 0}]
    leaves = list(out.get("leave_segments") or [])
    if not leaves and (
        out.get("leave_start") or float(out.get("used_comp_days") or 0)
    ):
        leaves = [
            {
                "start": out.get("leave_start") or "",
                "end": out.get("leave_end") or "",
                "used_days": out.get("used_comp_days") or 0,
            }
        ]
    out["travel_segments"] = travel
    out["ot_days"] = ot_days
    out["leave_segments"] = leaves
    return out


def _rebuild_travel(
    segments: list[dict[str, Any]],
    *,
    merge_gap_days: int,
) -> tuple[list[dict[str, Any]], float, str, str, str, str, str]:
    """Union travel segments, re-merge, recompute 30-day credits."""
    raw_pairs: list[tuple[date, date, date | None, date | None]] = []
    for seg in segments:
        act_s = _parse_date(seg.get("actual_start"))
        act_e = _parse_date(seg.get("actual_end"))
        if not act_s or not act_e:
            continue
        sys_s = _parse_date(seg.get("system_start")) or act_s
        sys_e = _parse_date(seg.get("system_end")) or act_e
        raw_pairs.append((sys_s, sys_e, act_s, act_e))

    act_pairs = [(a, b) for _, _, a, b in raw_pairs if a and b]
    merged_act = _merge_project_segments(act_pairs, merge_gap_days)

    travel_segments: list[dict[str, Any]] = []
    travel_comp = 0.0
    remarks: list[str] = []
    for a, b in merged_act:
        days = (b - a).days + 1
        credit = _travel_credit(days)
        travel_comp += credit
        overlapping = [
            (sa, sb, sc, sd)
            for sa, sb, sc, sd in raw_pairs
            if sc and sd and sc <= b and sd >= a
        ]
        seg_sys_s = min((sa for sa, _, _, _ in overlapping), default=a)
        seg_sys_e = max((sb for _, sb, _, _ in overlapping), default=b)
        travel_segments.append(
            {
                "system_start": seg_sys_s.isoformat(),
                "system_end": seg_sys_e.isoformat(),
                "actual_start": a.isoformat(),
                "actual_end": b.isoformat(),
                "credit": credit,
            }
        )
        if days >= 30:
            remarks.append(f"项目出差{days}天→{credit:g}天")
        elif days > 0:
            remarks.append(f"项目出差{days}天不足30不计")

    sys_start = ""
    sys_end = ""
    act_start = ""
    act_end = ""
    if raw_pairs:
        sys_start = min(a for a, _, _, _ in raw_pairs).isoformat()
        sys_end = max(b for _, b, _, _ in raw_pairs).isoformat()
    if merged_act:
        act_start = min(a for a, _ in merged_act).isoformat()
        act_end = max(b for _, b in merged_act).isoformat()
    return (
        travel_segments,
        travel_comp,
        sys_start,
        sys_end,
        act_start,
        act_end,
        "；".join(remarks),
    )


def _merge_ot(
    prior: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for d in current:
        key = str(d.get("date") or "")
        if key:
            by_date[key] = dict(d)
    for d in prior:
        key = str(d.get("date") or "")
        if key:
            by_date[key] = dict(d)  # prior wins
    return [by_date[k] for k in sorted(by_date.keys())]


def _merge_leave(
    prior: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for seg in current:
        key = (str(seg.get("start") or ""), str(seg.get("end") or ""))
        by_key[key] = dict(seg)
    for seg in prior:
        key = (str(seg.get("start") or ""), str(seg.get("end") or ""))
        by_key[key] = dict(seg)  # prior wins
    return [by_key[k] for k in sorted(by_key.keys())]


def _ot_labels(ot_days: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for d in ot_days:
        if float(d.get("credit") or 0) <= 0:
            continue
        label = str(d.get("date") or "")
        if d.get("holiday"):
            label += "(法定)"
        if label:
            labels.append(label)
    return "、".join(labels)


def merge_person_rows(
    prior: dict[str, Any] | None,
    current: dict[str, Any] | None,
    *,
    merge_gap_days: int = 1,
) -> dict[str, Any]:
    prior_s = synthesize_segments(prior) if prior else None
    current_s = synthesize_segments(current) if current else None
    base = dict(current_s or prior_s or {})
    name = (current_s or prior_s or {}).get("person_name") or ""
    center = ""
    department = ""
    if current_s:
        center = current_s.get("center") or ""
        department = current_s.get("department") or ""
    if not center and prior_s:
        center = prior_s.get("center") or ""
    if not department and prior_s:
        department = prior_s.get("department") or ""

    travel_in: list[dict[str, Any]] = []
    if prior_s:
        travel_in.extend(prior_s.get("travel_segments") or [])
    if current_s:
        travel_in.extend(current_s.get("travel_segments") or [])
    travel_segments, travel_comp, sys_s, sys_e, act_s, act_e, remark = _rebuild_travel(
        travel_in, merge_gap_days=merge_gap_days
    )

    ot_days = _merge_ot(
        list((prior_s or {}).get("ot_days") or []),
        list((current_s or {}).get("ot_days") or []),
    )
    leave_segments = _merge_leave(
        list((prior_s or {}).get("leave_segments") or []),
        list((current_s or {}).get("leave_segments") or []),
    )

    ot_comp = sum(float(d.get("credit") or 0) for d in ot_days)
    used = sum(float(s.get("used_days") or 0) for s in leave_segments)
    total = travel_comp + ot_comp
    leave_starts = [_parse_date(s.get("start")) for s in leave_segments]
    leave_ends = [_parse_date(s.get("end")) for s in leave_segments]
    leave_starts_f = [d for d in leave_starts if d]
    leave_ends_f = [d for d in leave_ends if d]

    base.update(
        {
            "person_name": name,
            "center": center,
            "department": department,
            "system_travel_start": sys_s,
            "system_travel_end": sys_e,
            "actual_travel_start": act_s,
            "actual_travel_end": act_e,
            "travel_comp_days": travel_comp,
            "ot_dates": _ot_labels(ot_days),
            "ot_comp_days": ot_comp,
            "total_comp_days": total,
            "leave_start": min(leave_starts_f).isoformat() if leave_starts_f else "",
            "leave_end": max(leave_ends_f).isoformat() if leave_ends_f else "",
            "used_comp_days": used,
            "remaining_comp_days": total - used,
            "remark": remark,
            "travel_segments": travel_segments,
            "ot_days": ot_days,
            "leave_segments": leave_segments,
        }
    )
    return base


def merge_ledger_rows(
    prior_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    merge_gap_days: int = 1,
) -> list[dict[str, Any]]:
    prior_by = {r.get("person_name"): r for r in prior_rows if r.get("person_name")}
    current_by = {r.get("person_name"): r for r in current_rows if r.get("person_name")}
    names = sorted(set(prior_by) | set(current_by))
    return [
        merge_person_rows(
            prior_by.get(name),
            current_by.get(name),
            merge_gap_days=merge_gap_days,
        )
        for name in names
    ]


def prior_ot_keys(prior_rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for person in prior_rows:
        name = str(person.get("person_name") or "")
        for d in synthesize_segments(person).get("ot_days") or []:
            date_s = str(d.get("date") or "")
            if name and date_s:
                keys.add((name, date_s.replace("(法定)", "").strip()[:10]))
    return keys


def filter_warnings_covered_by_prior(
    warnings: list[dict[str, Any]] | None,
    prior_keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in warnings or []:
        detail = w.get("detail") or {}
        person = str(detail.get("person") or "")
        date_s = str(detail.get("date") or "")[:10]
        code = w.get("code") or ""
        if (
            code in ("ot_missing_punch", "ot_half_day_mismatch")
            and person
            and date_s
            and (person, date_s) in prior_keys
        ):
            continue
        out.append(w)
    return out
