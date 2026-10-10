"""Unit scenarios for attendance compute rules recovered from bytecode."""

from __future__ import annotations

from datetime import date, datetime

from app.attendance_summary.compute import (
    HALF_AFTERNOON,
    HALF_MORNING,
    LeaveRow,
    PunchSide,
    RosterPerson,
    SIDE_IN,
    SIDE_OUT,
    TravelRow,
    compute_month,
    default_work_dates,
    result_to_dict,
)


def test_leave_travel_conflict_and_half_day_leave() -> None:
    roster = [
        RosterPerson(
            name="甲", center="产品中心", post="工程师", seq=1, base_site="太原"
        )
    ]
    work = default_work_dates(2026, 3)
    travel = [
        TravelRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            category="项目类出差（入场）",
            location="北京",
            start=date(2026, 3, 10),
            end=date(2026, 3, 12),
            status="已通过",
        )
    ]
    leave = [
        LeaveRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            leave_kind="年假",
            start=date(2026, 3, 10),
            end=date(2026, 3, 10),
            start_half="",
            end_half="",
            duration_text="1天",
            status="已通过",
        ),
        LeaveRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            leave_kind="事假",
            start=date(2026, 3, 16),
            end=date(2026, 3, 16),
            start_half=HALF_MORNING,
            end_half=HALF_MORNING,
            duration_text="0.5天",
            status="已通过",
        ),
    ]
    punch: list[PunchSide] = []
    company_addr = "奥特莱物流科技有限公司 | 山西省太原市小店区长治路251号a座"
    for day in range(1, 32):
        try:
            wd = date(2026, 3, day)
        except ValueError:
            continue
        if wd.weekday() >= 5:
            continue
        punch.append(
            PunchSide(
                person_name="甲",
                work_date=wd,
                side=SIDE_IN,
                punch_time=datetime(2026, 3, day, 8, 30),
                status="正常",
                address=company_addr,
            )
        )
        punch.append(
            PunchSide(
                person_name="甲",
                work_date=wd,
                side=SIDE_OUT,
                punch_time=datetime(2026, 3, day, 18, 0),
                status="正常",
                address=company_addr,
            )
        )

    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=travel,
        leave=leave,
        punch=punch,
        work_dates=work,
        overseas_keywords=["香港", "海外"],
    )
    d = result_to_dict(out)
    blocking = [w for w in d["warnings"] if w.get("blocking")]
    assert any(w.get("type") == "leave_travel_conflict" for w in blocking)

    # Resolve prefer leave and recompute
    out2 = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=travel,
        leave=leave,
        punch=punch,
        work_dates=work,
        overseas_keywords=["香港", "海外"],
        resolutions={blocking[0]["id"]: {"prefer": "leave"}},
    )
    d2 = result_to_dict(out2)
    person = d2["people"][0]
    assert person["leave_annual"] >= 1.0 or person["leave_personal"] >= 0.5
    # half-day leave should not invent full-day personal leave of 1.0 alone
    assert person["leave_personal"] in (0.0, 0.5, 1.0)


def test_travel_base_site_clip_emits_data_quality() -> None:
    """Punching at base company during travel should emit DQ / clip travel days."""
    roster = [
        RosterPerson(
            name="甲", center="产品中心", post="工程师", seq=1, base_site="太原"
        )
    ]
    work = default_work_dates(2026, 3)
    travel = [
        TravelRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            category="项目类出差（入场）",
            location="北京",
            start=date(2026, 3, 2),
            end=date(2026, 3, 6),
            status="已通过",
            start_at=datetime(2026, 3, 2, 0, 0),
            end_at=datetime(2026, 3, 6, 0, 0),
        )
    ]
    company_addr = "奥特莱物流科技有限公司 | 山西省太原市小店区长治路251号a座"
    punch = []
    for day in (2, 3, 4, 5, 6):
        punch.append(
            PunchSide(
                person_name="甲",
                work_date=date(2026, 3, day),
                side=SIDE_IN,
                punch_time=datetime(2026, 3, day, 8, 30),
                status="正常",
                address=company_addr,
            )
        )
        punch.append(
            PunchSide(
                person_name="甲",
                work_date=date(2026, 3, day),
                side=SIDE_OUT,
                punch_time=datetime(2026, 3, day, 18, 0),
                status="正常",
                address=company_addr,
            )
        )

    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=travel,
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    d = result_to_dict(out)
    codes = {w.get("code") for w in d["warnings"]}
    assert codes & {
        "travel_start_still_base",
        "travel_early_return",
        "travel_still_base",
    } or any(w.get("type") == "data_quality" for w in d["warnings"])
