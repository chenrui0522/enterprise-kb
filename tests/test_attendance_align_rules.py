"""Domain rules for align-attendance-to-correct-ledger."""

from __future__ import annotations

from datetime import date, datetime, time

from app.attendance_summary.compare_ledger import load_exemptions
from app.attendance_summary.compute import (
    LeaveRow,
    PunchSide,
    RosterPerson,
    SIDE_IN,
    SIDE_OUT,
    TravelRow,
    apply_default_base_site,
    compute_month,
    default_work_dates,
    normalize_person_name,
    person_name_marked_departed,
    result_to_dict,
)

COMPANY = "奥特莱物流科技有限公司 | 山西省太原市小店区长治路251号a座"
BEIJING = "北京市朝阳区某客户现场"


def _punch_day(
    name: str, d: date, *, addr: str = COMPANY, out_hour: int = 18, out_min: int = 0
) -> list[PunchSide]:
    return [
        PunchSide(
            person_name=name,
            work_date=d,
            side=SIDE_IN,
            punch_time=datetime(d.year, d.month, d.day, 8, 30),
            status="正常",
            address=addr,
        ),
        PunchSide(
            person_name=name,
            work_date=d,
            side=SIDE_OUT,
            punch_time=datetime(d.year, d.month, d.day, out_hour, out_min),
            status="正常",
            address=addr,
        ),
    ]


def test_travel_day_punched_side_travel_missing_side_keeps_queka() -> None:
    """出差日：有卡侧￥，缺卡侧×（须补卡抵消）；不得写成 ￥/￥。"""
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    work = default_work_dates(2026, 8) | {date(2026, 8, 8), date(2026, 8, 22)}
    travel = [
        TravelRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            category="非项目类出差",
            location="朔州",
            start=date(2026, 8, 27),
            end=date(2026, 8, 27),
            status="已通过",
            start_at=datetime(2026, 8, 27, 7, 0),
            end_at=datetime(2026, 8, 27, 19, 30),
        )
    ]
    punch = [
        PunchSide(
            person_name="甲",
            work_date=date(2026, 8, 27),
            side=SIDE_IN,
            punch_time=datetime(2026, 8, 27, 8, 19),
            status="正常｜人脸识别",
            address="前进西街 | 山西省忻州市原平市前进西街",
            leave_apply="出差12.5小时（8/27 07:00 - 8/27 19:30）",
        ),
        PunchSide(
            person_name="甲",
            work_date=date(2026, 8, 27),
            side=SIDE_OUT,
            punch_time=None,
            status="缺卡（18:00）",
            address="",
            leave_apply="出差12.5小时（8/27 07:00 - 8/27 19:30）",
        ),
    ]
    out = compute_month(
        year=2026,
        month=8,
        roster=roster,
        travel=travel,
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    person = result_to_dict(out)["people"][0]
    sym = person["day_symbols"].get("27") or person["day_symbols"].get(27)
    assert sym == {"in": "￥", "out": "×"}


def test_exemptions_load_has_zhangnanjie() -> None:
    items = load_exemptions()
    assert any(x.get("person") == "张楠杰" for x in items)


def test_default_base_site_only_when_empty() -> None:
    empty = RosterPerson(name="甲", center="c", post="p", seq=1, base_site="")
    filled = RosterPerson(name="乙", center="c", post="p", seq=2, base_site="苏州")
    out = apply_default_base_site([empty, filled], default_base_site="太原")
    assert out[0].base_site == "太原"
    assert out[1].base_site == "苏州"


def test_departed_name_markers() -> None:
    assert person_name_marked_departed("张三（已离职）")
    assert person_name_marked_departed("张三（离职）")
    assert person_name_marked_departed("张三(离职)")
    assert normalize_person_name("张三（离职）") == "张三"
    assert not person_name_marked_departed("张三")


def test_late_depart_covers_start_day() -> None:
    """Departure at/after 18:00 on start day still counts as travel day."""
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    work = default_work_dates(2026, 3)
    # Mon 2026-03-02
    travel = [
        TravelRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            category="项目类出差（入场）",
            location="北京",
            start=date(2026, 3, 2),
            end=date(2026, 3, 4),
            status="已通过",
            start_at=datetime(2026, 3, 2, 18, 30),
            end_at=datetime(2026, 3, 4, 18, 0),
        )
    ]
    punch: list[PunchSide] = []
    # company morning then leave late for travel
    punch += _punch_day("甲", date(2026, 3, 2), addr=COMPANY, out_hour=18, out_min=30)
    punch += _punch_day("甲", date(2026, 3, 3), addr=BEIJING)
    punch += _punch_day("甲", date(2026, 3, 4), addr=BEIJING)

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
    person = result_to_dict(out)["people"][0]
    # late depart ≥18:00 on start day still counts a full travel day
    assert person["travel_domestic"] >= 1.0
    sym = person["day_symbols"].get(2) or person["day_symbols"].get("2")
    assert sym is not None
    joined = f"{sym}" if not isinstance(sym, dict) else f"{sym.get('in','')}/{sym.get('out','')}"
    assert "￥" in joined or "＄" in joined or person["travel_domestic"] >= 2.0


def test_base_site_clip_company_days_not_all_travel() -> None:
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="")
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
            start_at=datetime(2026, 3, 2, 9, 0),
            end_at=datetime(2026, 3, 6, 18, 0),
        )
    ]
    punch: list[PunchSide] = []
    for day in (2, 3, 4, 5, 6):
        punch += _punch_day("甲", date(2026, 3, day), addr=COMPANY)

    out = compute_month(
        year=2026,
        month=3,
        roster=roster,  # empty -> default 太原
        travel=travel,
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    person = result_to_dict(out)["people"][0]
    # All days at base company: travel count should be clipped below full 5
    assert person["travel_domestic"] < 5


def test_leave_apply_remote_counts_as_travel_not_leave() -> None:
    """Punch 假勤申请含出差 + 外地点 → 出差列，不进休假分列。"""
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    work = default_work_dates(2026, 3)
    d = date(2026, 3, 10)
    punch = [
        PunchSide(
            person_name="甲",
            work_date=d,
            side=SIDE_IN,
            punch_time=datetime(2026, 3, 10, 8, 30),
            status="正常",
            address=BEIJING,
            leave_apply="假勤申请出差：赴北京客户现场",
        ),
        PunchSide(
            person_name="甲",
            work_date=d,
            side=SIDE_OUT,
            punch_time=datetime(2026, 3, 10, 18, 0),
            status="正常",
            address=BEIJING,
            leave_apply="假勤申请出差：赴北京客户现场",
        ),
    ]
    for day in range(1, 32):
        try:
            wd = date(2026, 3, day)
        except ValueError:
            continue
        if wd.weekday() >= 5 or wd == d:
            continue
        punch += _punch_day("甲", wd)

    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=[],
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    person = result_to_dict(out)["people"][0]
    assert person["travel_domestic"] >= 1.0
    assert person["leave_personal"] == 0.0
    assert person["present_days"] >= 1.0


def test_local_personal_leave_not_travel() -> None:
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    work = default_work_dates(2026, 3)
    leave = [
        LeaveRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            leave_kind="事假",
            start=date(2026, 3, 10),
            end=date(2026, 3, 10),
            start_half="",
            end_half="",
            duration_text="1天",
            status="已通过",
        )
    ]
    punch: list[PunchSide] = []
    for day in range(1, 32):
        try:
            wd = date(2026, 3, day)
        except ValueError:
            continue
        if wd.weekday() >= 5 or wd == date(2026, 3, 10):
            continue
        punch += _punch_day("甲", wd)

    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=[],
        leave=leave,
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    person = result_to_dict(out)["people"][0]
    assert person["leave_personal"] >= 1.0
    assert person["travel_domestic"] == 0.0


def test_departed_cutoff_skips_after_last_punch() -> None:
    roster = [
        RosterPerson(
            name="甲（离职）", center="产品中心", post="工程师", seq=1, base_site="太原"
        )
    ]
    work = default_work_dates(2026, 3)
    punch = _punch_day("甲", date(2026, 3, 10))
    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=[],
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    person = result_to_dict(out)["people"][0]
    # After 3/10, weekdays should not accumulate absent/missing for departed
    # present days should not include late March weekdays without punches as full absent stack
    assert person["present_days"] <= 5


def test_non_company_punch_requires_resolution() -> None:
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    # Saturday not in work dates
    work = {date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6)}
    sat = date(2026, 3, 7)  # Saturday
    assert sat not in work
    punch = _punch_day("甲", sat) + _punch_day("甲", date(2026, 3, 2))
    out = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=[],
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
    )
    d = result_to_dict(out)
    blocking = [w for w in d["warnings"] if w.get("blocking")]
    assert any("non_company" in str(w.get("id")) or w.get("type") == "non_company_punch_present" for w in blocking)

    wid = next(w["id"] for w in blocking if "non_company" in str(w.get("id")))
    out_ignore = compute_month(
        year=2026,
        month=3,
        roster=roster,
        travel=[],
        leave=[],
        punch=punch,
        work_dates=work,
        overseas_keywords=[],
        resolutions={wid: {"prefer": "ignore"}},
    )
    d2 = result_to_dict(out_ignore)
    still = [
        w
        for w in d2["warnings"]
        if w.get("id") == wid and w.get("blocking")
    ]
    assert not still
    # ignore must not add present for that Saturday
    person = d2["people"][0]
    assert person["present_days"] == result_to_dict(out)["people"][0]["present_days"] or person["present_days"] <= 1.0


def test_field_punch_after_travel_end_still_counts_domestic() -> None:
    """审批止于前一日，应出勤日仍外勤打卡 → 合成国内出差（张霄鹏 8/31 类）。"""
    roster = [
        RosterPerson(name="甲", center="产品中心", post="工程师", seq=1, base_site="太原")
    ]
    work = default_work_dates(2026, 3)
    travel = [
        TravelRow(
            applicant="甲",
            department="产品中心",
            center="产品中心",
            category="项目类出差（入场）",
            location="广东佛山",
            start=date(2026, 3, 2),
            end=date(2026, 3, 10),
            status="已通过",
            start_at=datetime(2026, 3, 2, 8, 0),
            end_at=datetime(2026, 3, 10, 18, 0),
        )
    ]
    foshan = "天泰东三路 | 广东省佛山市三水区天泰东三路"
    punch: list[PunchSide] = []
    for day in range(2, 11):
        punch += _punch_day("甲", date(2026, 3, day), addr=foshan)
    # 3/11 审批已结束但仍在外地
    punch += _punch_day("甲", date(2026, 3, 11), addr=foshan)

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
    person = result_to_dict(out)["people"][0]
    sym = person["day_symbols"].get(11) or person["day_symbols"].get("11")
    assert sym is not None
    joined = (
        f"{sym}"
        if not isinstance(sym, dict)
        else f"{sym.get('in', '')}/{sym.get('out', '')}"
    )
    assert "￥" in joined
    # at least approval span workdays + the extra field day
    assert person["travel_domestic"] >= 8.0
