"""Pure rules engine: travel / overtime / leave → ledger rows + warnings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.leave_ledger.config_data import is_hq_address
from app.leave_ledger.parse import LeaveRecord, OvertimeDay, ParsedSources, PunchRecord, TravelRecord


@dataclass
class WarningItem:
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True


OT_RESOLUTION_CREDITS = {
    "exclude": 0.0,
    "accept_half": 0.5,
    "accept_full": 1.0,
}


@dataclass
class LedgerRow:
    person_name: str
    center: str
    department: str
    system_travel_start: str = ""
    system_travel_end: str = ""
    actual_travel_start: str = ""
    actual_travel_end: str = ""
    travel_comp_days: float = 0.0
    ot_dates: str = ""
    ot_comp_days: float = 0.0
    total_comp_days: float = 0.0
    leave_start: str = ""
    leave_end: str = ""
    used_comp_days: float = 0.0
    remaining_comp_days: float = 0.0
    remark: str = ""
    travel_segments: list[dict[str, Any]] = field(default_factory=list)
    ot_days: list[dict[str, Any]] = field(default_factory=list)
    leave_segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ComputeResult:
    rows: list[LedgerRow]
    warnings: list[WarningItem]
    totals: dict[str, Any] = field(default_factory=dict)


def _is_project_travel(category: str) -> bool:
    return "项目" in (category or "") and "非项目" not in (category or "")


def _is_non_project_travel(category: str) -> bool:
    return "非项目" in (category or "")


def _approved(status: str) -> bool:
    return "已通过" in (status or "") or status == "通过"


def _daterange(start: date, end: date) -> list[date]:
    if end < start:
        return []
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _punch_index(
    punches: list[PunchRecord],
) -> dict[tuple[str, date], list[PunchRecord]]:
    idx: dict[tuple[str, date], list[PunchRecord]] = {}
    for p in punches:
        idx.setdefault((p.person_name, p.work_date), []).append(p)
    return idx


def _truncate_travel_end(
    person: str,
    start: date,
    end: date,
    punch_idx: dict[tuple[str, date], list[PunchRecord]],
    hq_keywords: list[str],
    warnings: list[WarningItem],
) -> date:
    actual_end = end
    unknown_addr = False
    for d in _daterange(start, end):
        punches = punch_idx.get((person, d), [])
        for p in punches:
            if not p.address:
                continue
            if is_hq_address(p.address, hq_keywords):
                # first HQ punch day becomes actual end
                if d < actual_end:
                    actual_end = d
                break
            # address present but not HQ — ok (on trip)
            if not any(k in p.address for k in hq_keywords) and p.address:
                pass
        # if all punches that day have empty address while on reported travel
        if punches and all(not p.address for p in punches):
            unknown_addr = True
    if unknown_addr:
        warnings.append(
            WarningItem(
                code="hq_address_unknown",
                message=f"{person} 出差期间存在无地址打卡，无法完整判定回司",
                detail={"person": person, "start": start.isoformat(), "end": end.isoformat()},
            )
        )
    return actual_end


def _merge_project_segments(
    segments: list[tuple[date, date]],
    gap_days: int,
) -> list[tuple[date, date]]:
    if not segments:
        return []
    segs = sorted(segments, key=lambda x: x[0])
    merged: list[tuple[date, date]] = [segs[0]]
    for start, end in segs[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + timedelta(days=gap_days + 1):
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def _leave_days(rec: LeaveRecord) -> float:
    text = rec.duration_text or ""
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*天", text)
    if m:
        return float(m.group(1))
    if rec.start and rec.end:
        return float((rec.end - rec.start).days + 1)
    if rec.start or rec.end:
        return 1.0
    return 0.0


def _complete_leave_bounds(
    start: date | None, end: date | None, used_days: float
) -> tuple[date | None, date | None]:
    """Fill missing leave end/start from duration so export always has dates."""
    import math

    if start and end:
        return start, end
    if start and not end:
        if used_days <= 0:
            return start, start
        span = max(int(math.ceil(used_days)) - 1, 0)
        return start, start + timedelta(days=span)
    if end and not start:
        if used_days <= 0:
            return end, end
        span = max(int(math.ceil(used_days)) - 1, 0)
        return end - timedelta(days=span), end
    return start, end


def _ot_day_hours(ot: OvertimeDay) -> float:
    return float(ot.hours or 0.0)


def _punch_span_hours(punches: list[PunchRecord]) -> float | None:
    times = [p.punch_time for p in punches if p.punch_time]
    if len(times) < 2:
        return 0.0 if times else None
    delta = (max(times) - min(times)).total_seconds() / 3600.0
    return max(delta, 0.0)


def _date_in_segments(day: date, segments: list[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in segments)


def _record_ot_day(
    *,
    ot_days: list[dict[str, Any]],
    ot_dates: list[str],
    work_date: date,
    credit: float,
    holidays: set[date],
) -> float:
    is_hol = work_date in holidays
    ot_days.append(
        {
            "date": work_date.isoformat(),
            "credit": credit,
            "holiday": is_hol,
        }
    )
    if credit > 0:
        label = work_date.isoformat()
        if is_hol:
            label += "(法定)"
        ot_dates.append(label)
    return credit


def compute_ledger(
    parsed: ParsedSources,
    *,
    present_roles: set[str],
    hq_keywords: list[str],
    holidays: set[date] | None,
    full_day_hours: float = 8.0,
    half_day_hours: float = 4.0,
    merge_gap_days: int = 1,
    include_unapproved: set[str] | None = None,
    ot_resolutions: dict[tuple[str, str], str] | None = None,
) -> ComputeResult:
    """Compute compensatory leave ledger rows and warnings.

    ``include_unapproved`` holds warning keys already resolved to include.
    ``ot_resolutions`` maps ``(person, date_iso)`` to exclude|accept_half|accept_full.
    """
    warnings: list[WarningItem] = []
    include_unapproved = include_unapproved or set()
    ot_resolutions = ot_resolutions or {}

    for role in ("travel", "overtime", "leave", "punch"):
        if role not in present_roles:
            warnings.append(
                WarningItem(
                    code=f"missing_source_{role}",
                    message=f"缺少源文件：{role}",
                    detail={"role": role},
                )
            )

    if holidays is None:
        warnings.append(
            WarningItem(
                code="holidays_calendar_missing",
                message="未配置法定假日表，出差段内法定假日加班加成将跳过",
                detail={},
                blocking=False,
            )
        )
        holidays = set()

    punch_idx = _punch_index(parsed.punch)

    # Person profiles
    people: dict[str, dict[str, str]] = {}

    def _touch(name: str, center: str = "", dept: str = "") -> None:
        info = people.setdefault(name, {"center": "", "department": ""})
        if center and not info["center"]:
            info["center"] = center
        if dept and not info["department"]:
            info["department"] = dept

    project_segs: dict[str, list[tuple[date, date, date, date]]] = {}
    # (system_start, system_end, actual_start, actual_end)

    for t in parsed.travel:
        _touch(t.applicant, t.center, t.department)
        key = f"travel:{t.applicant}:{t.approval_id or t.start}:{t.status}"
        if not _approved(t.status):
            wkey = f"approval_not_passed:{key}"
            warnings.append(
                WarningItem(
                    code="approval_not_passed",
                    message=f"{t.applicant} 出差审批状态为「{t.status}」未计入（除非决议纳入）",
                    detail={"person": t.applicant, "kind": "travel", "status": t.status, "key": wkey},
                )
            )
            if wkey not in include_unapproved:
                continue
        if not t.start or not t.end:
            warnings.append(
                WarningItem(
                    code="travel_missing_dates",
                    message=f"{t.applicant} 出差缺少起止日期",
                    detail={"person": t.applicant},
                )
            )
            continue
        if _is_project_travel(t.category):
            actual_end = _truncate_travel_end(
                t.applicant, t.start, t.end, punch_idx, hq_keywords, warnings
            )
            project_segs.setdefault(t.applicant, []).append(
                (t.start, t.end, t.start, actual_end)
            )
        elif _is_non_project_travel(t.category):
            # no travel-day credit; OT handled below
            pass
        else:
            warnings.append(
                WarningItem(
                    code="travel_category_unknown",
                    message=f"{t.applicant} 出差类别无法识别：{t.category}",
                    detail={"person": t.applicant, "category": t.category},
                    blocking=False,
                )
            )

    # Overtime days
    ot_by_person: dict[str, list[OvertimeDay]] = {}
    for ot in parsed.overtime:
        _touch(ot.applicant, ot.center, ot.department)
        key = f"ot:{ot.applicant}:{ot.work_date.isoformat()}:{ot.approval_id}"
        if not _approved(ot.status):
            wkey = f"approval_not_passed:{key}"
            warnings.append(
                WarningItem(
                    code="approval_not_passed",
                    message=f"{ot.applicant} 加班审批状态为「{ot.status}」未计入",
                    detail={"person": ot.applicant, "kind": "overtime", "key": wkey},
                )
            )
            if wkey not in include_unapproved:
                continue
        ot_by_person.setdefault(ot.applicant, []).append(ot)

    # Leave (comp only)
    leave_by_person: dict[str, list[LeaveRecord]] = {}
    for lv in parsed.leave:
        _touch(lv.applicant, lv.center, lv.department)
        if "调休" not in (lv.leave_kind or ""):
            continue
        key = f"leave:{lv.applicant}:{lv.approval_id}:{lv.start}"
        if not _approved(lv.status):
            wkey = f"approval_not_passed:{key}"
            warnings.append(
                WarningItem(
                    code="approval_not_passed",
                    message=f"{lv.applicant} 调休假审批状态为「{lv.status}」未计入",
                    detail={"person": lv.applicant, "kind": "leave", "key": wkey},
                )
            )
            if wkey not in include_unapproved:
                continue
        leave_by_person.setdefault(lv.applicant, []).append(lv)

    rows: list[LedgerRow] = []

    all_names = sorted(
        set(people)
        | set(project_segs)
        | set(ot_by_person)
        | set(leave_by_person)
    )

    for name in all_names:
        info = people.get(name, {"center": "", "department": ""})
        # Travel segments
        raw_segs = project_segs.get(name, [])
        act_pairs = [(c, d) for _, _, c, d in raw_segs]
        merged_act = _merge_project_segments(act_pairs, merge_gap_days)

        travel_comp = 0.0
        travel_remarks: list[str] = []
        travel_segments: list[dict[str, Any]] = []
        sys_start = ""
        sys_end = ""
        act_start = ""
        act_end = ""
        if raw_segs:
            sys_start = min(a for a, _, _, _ in raw_segs).isoformat()
            sys_end = max(b for _, b, _, _ in raw_segs).isoformat()
        if merged_act:
            act_start = min(a for a, _ in merged_act).isoformat()
            act_end = max(b for _, b in merged_act).isoformat()
        for a, b in merged_act:
            days = (b - a).days + 1
            blocks = days // 30
            credit = float(blocks * 2)
            travel_comp += credit
            overlapping = [
                (sa, sb, sc, sd)
                for sa, sb, sc, sd in raw_segs
                if sc <= b and sd >= a
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
                travel_remarks.append(f"项目出差{days}天→{credit:g}天")
            elif days > 0:
                travel_remarks.append(f"项目出差{days}天不足30不计")

        # OT compensatory days (with punch alignment + resolutions).
        # Rule 2: during project actual travel, only statutory-holiday OT days count.
        # Rule 3: outside project travel (incl. non-project), dual-evidence OT days count.
        ot_comp = 0.0
        ot_dates: list[str] = []
        ot_days: list[dict[str, Any]] = []
        for ot in ot_by_person.get(name, []):
            date_key = ot.work_date.isoformat()
            action = ot_resolutions.get((name, date_key))
            if action in OT_RESOLUTION_CREDITS:
                credit = OT_RESOLUTION_CREDITS[action]
                ot_comp += _record_ot_day(
                    ot_days=ot_days,
                    ot_dates=ot_dates,
                    work_date=ot.work_date,
                    credit=credit,
                    holidays=holidays,
                )
                continue

            in_project_travel = _date_in_segments(ot.work_date, merged_act)
            if in_project_travel and ot.work_date not in holidays:
                # Not a statutory holiday inside project travel → no OT credit.
                continue

            punches = punch_idx.get((name, ot.work_date), [])
            if not punches:
                warnings.append(
                    WarningItem(
                        code="ot_missing_punch",
                        message=f"{name} {date_key} 有加班申请无打卡",
                        detail={
                            "person": name,
                            "date": date_key,
                        },
                    )
                )
                _record_ot_day(
                    ot_days=ot_days,
                    ot_dates=ot_dates,
                    work_date=ot.work_date,
                    credit=0.0,
                    holidays=holidays,
                )
                continue
            span = _punch_span_hours(punches)
            hours = _ot_day_hours(ot)
            if hours >= full_day_hours and span is not None and span < half_day_hours:
                warnings.append(
                    WarningItem(
                        code="ot_half_day_mismatch",
                        message=(
                            f"{name} {date_key} 加班申请约 {hours}h "
                            f"但打卡跨度约 {span:.1f}h，须复核"
                        ),
                        detail={
                            "person": name,
                            "date": date_key,
                            "hours": hours,
                            "punch_span": span,
                        },
                    )
                )
                _record_ot_day(
                    ot_days=ot_days,
                    ot_dates=ot_dates,
                    work_date=ot.work_date,
                    credit=0.0,
                    holidays=holidays,
                )
                continue
            ot_comp += _record_ot_day(
                ot_days=ot_days,
                ot_dates=ot_dates,
                work_date=ot.work_date,
                credit=1.0,
                holidays=holidays,
            )

        used = 0.0
        leave_s = ""
        leave_e = ""
        leave_segments: list[dict[str, Any]] = []
        leaves = leave_by_person.get(name, [])
        if leaves:
            for lv in leaves:
                days_used = _leave_days(lv)
                if days_used <= 0:
                    continue
                used += days_used
                seg_start, seg_end = _complete_leave_bounds(lv.start, lv.end, days_used)
                leave_segments.append(
                    {
                        "start": seg_start.isoformat() if seg_start else "",
                        "end": seg_end.isoformat() if seg_end else "",
                        "used_days": days_used,
                    }
                )
            starts = [
                date.fromisoformat(s["start"])
                for s in leave_segments
                if s.get("start")
            ]
            ends = [
                date.fromisoformat(s["end"]) for s in leave_segments if s.get("end")
            ]
            if starts:
                leave_s = min(starts).isoformat()
            if ends:
                leave_e = max(ends).isoformat()

        total = travel_comp + ot_comp
        remaining = total - used
        remark = "；".join(travel_remarks)

        # Emit a row if any signal
        if not (raw_segs or ot_by_person.get(name) or leaves):
            continue

        rows.append(
            LedgerRow(
                person_name=name,
                center=info.get("center", ""),
                department=info.get("department", ""),
                system_travel_start=sys_start,
                system_travel_end=sys_end,
                actual_travel_start=act_start,
                actual_travel_end=act_end,
                travel_comp_days=travel_comp,
                ot_dates="、".join(ot_dates),
                ot_comp_days=ot_comp,
                total_comp_days=total,
                leave_start=leave_s,
                leave_end=leave_e,
                used_comp_days=used,
                remaining_comp_days=remaining,
                remark=remark,
                travel_segments=travel_segments,
                ot_days=ot_days,
                leave_segments=leave_segments,
            )
        )

    return ComputeResult(
        rows=rows,
        warnings=warnings,
        totals={
            "person_count": len(rows),
            "total_comp_days": sum(r.total_comp_days for r in rows),
            "used_comp_days": sum(r.used_comp_days for r in rows),
        },
    )


def compute_result_to_dict(result: ComputeResult) -> dict[str, Any]:
    return {
        "rows": [asdict(r) for r in result.rows],
        "warnings": [asdict(w) for w in result.warnings],
        "totals": result.totals,
    }


def warnings_from_dict(items: list[dict[str, Any]] | None) -> list[WarningItem]:
    out: list[WarningItem] = []
    for item in items or []:
        out.append(
            WarningItem(
                code=str(item.get("code") or ""),
                message=str(item.get("message") or ""),
                detail=dict(item.get("detail") or {}),
                blocking=bool(item.get("blocking", True)),
            )
        )
    return out
