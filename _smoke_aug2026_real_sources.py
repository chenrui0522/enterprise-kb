"""Smoke Aug 2026 with real Desktop sources + calendar/resolution fixes."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.attendance_summary import service as att_service
from app.core.config import get_settings
from app.core.db import Base
from app.core.errors import AppError
from app.identity.constants import (
    PERM_ATTENDANCE_SUMMARY_READ,
    PERM_ATTENDANCE_SUMMARY_WRITE,
    PERM_CHAT_USE,
)
from app.identity.principal import Principal
import app.models.attendance_summary  # noqa: F401
import app.models.entity  # noqa: F401
import app.models.identity  # noqa: F401

BASE = Path(r"c:\Users\chenr\Desktop\奥特莱多智能体项目资料汇总‘\AI考勤统计")
FILES = {
    "travel": BASE / "【审批】出差申请（太原公司）2026.07.19-2026.09.02jm.xlsx",
    "leave": BASE / "【审批】请假申请（太原公司）2026.08.01-2026.08.31 (1)jm.xlsx",
    "punch": BASE / "上下班打卡_日报_20260801-20260831 (5)jm.xlsx",
    "roster": BASE / "太原花名册-2026年8月底表.xlsx",
}
OUT = Path(r"c:\Users\chenr\AppData\Local\Temp\recovery\aug2026_smoke2")
MANUAL_PATH = Path("非出勤日打卡-人工决议.json")
WORKDAY_WEEKENDS = {"2026-08-08", "2026-08-22"}


def _principal() -> Principal:
    return Principal(
        user_id="u-smoke",
        tenant_id="autley",
        username="ops",
        display_name="Ops",
        site="taiyuan",
        clearance="general",
        permissions=(
            PERM_CHAT_USE,
            PERM_ATTENDANCE_SUMMARY_READ,
            PERM_ATTENDANCE_SUMMARY_WRITE,
        ),
        attendance_summary_org_ok=True,
    )


def _normalize_dates(items) -> set[str]:
    out: set[str] = set()
    for raw in items or []:
        s = str(raw).strip().replace("/", "-")
        if not s:
            continue
        parts = s.split("-")
        if len(parts) == 3:
            y, m, d = parts
            out.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
        else:
            out.add(s)
    return out


async def main() -> None:
    for p in FILES.values():
        if not p.is_file():
            raise SystemExit(f"missing: {p}")
    OUT.mkdir(parents=True, exist_ok=True)
    storage = OUT / "storage"
    storage.mkdir(exist_ok=True)
    os.environ["KB_DOCUMENT_STORAGE_DIR"] = str(storage)
    get_settings.cache_clear()

    manual = {}
    if MANUAL_PATH.is_file():
        manual = json.loads(MANUAL_PATH.read_text(encoding="utf-8"))

    engine = create_async_engine(f"sqlite+aiosqlite:///{OUT / 'att.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    principal = _principal()

    async with factory() as session:
        job = await att_service.create_job(session, principal, year=2026, month=8)
        print("job", job.id)

        job = await att_service.cold_start_roster_from_hr(
            session,
            principal,
            job.id,
            filename=FILES["roster"].name,
            data=FILES["roster"].read_bytes(),
        )
        print("roster", len(job.roster or []))

        for role in ("travel", "leave", "punch"):
            path = FILES[role]
            job = await att_service.upload_source(
                session,
                principal,
                job.id,
                filename=path.name,
                data=path.read_bytes(),
                role=role,
            )
            print("uploaded", role)

        job = await att_service.confirm_period(
            session, principal, job.id, acknowledge_incomplete_month=True
        )

        draft = att_service.calendar_draft_for_job(job)
        print("draft_keys", sorted(draft.keys()) if isinstance(draft, dict) else type(draft))
        non_work = _normalize_dates(
            (draft or {}).get("non_work_dates")
            or (draft or {}).get("non_work")
            or (draft or {}).get("draft_non_work_dates")
            or getattr(job, "non_work_dates", None)
            or []
        )
        print(
            "before non_work has weekends",
            WORKDAY_WEEKENDS & non_work,
            "count",
            len(non_work),
        )
        non_work -= WORKDAY_WEEKENDS

        if hasattr(att_service, "set_non_work_working_set"):
            job = await att_service.set_non_work_working_set(
                session, principal, job.id, non_work_dates=sorted(non_work)
            )
            print("set_non_work_working_set", len(non_work))

        job = await att_service.confirm_calendar(
            session, principal, job.id, use_draft=False, non_work_dates=sorted(non_work)
        )
        print("calendar confirmed")

        job = await att_service.recompute(session, principal, job.id)
        warns = (job.compute_result or {}).get("warnings") or []
        blocking = [w for w in warns if w.get("blocking")]
        print(
            "recompute people",
            len((job.compute_result or {}).get("people") or []),
            "blocking",
            len(blocking),
            "quality",
            len([w for w in warns if not w.get("blocking")]),
        )

        for w in list(blocking):
            wid = w["id"]
            prefer = (manual.get(wid) or {}).get("prefer")
            if not prefer:
                if w.get("type") == "leave_travel_conflict":
                    prefer = "travel"
                else:
                    prefer = "present"
            try:
                job = await att_service.resolve_conflict(
                    session, principal, job.id, warning_id=wid, prefer=prefer
                )
            except Exception as e:
                print("resolve_fail", wid, prefer, type(e).__name__, e)

        job = await att_service.recompute(session, principal, job.id)
        blocking = [
            w
            for w in ((job.compute_result or {}).get("warnings") or [])
            if w.get("blocking")
        ]
        print("after_resolve_blocking", len(blocking))
        if blocking:
            (OUT / "still_blocking.json").write_text(
                json.dumps(blocking, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("still", [w["id"] for w in blocking[:12]])

        try:
            await att_service.export_formal(session, principal, job.id)
            print("UNEXPECTED formal before confirm")
        except AppError as e:
            print("formal_rejected_ok", e.message)

        preview = await att_service.export_preview(session, principal, job.id)
        (OUT / "preview.xlsx").write_bytes(preview)
        print("preview_bytes", len(preview))

        job = await att_service.acknowledge_data_quality(
            session, principal, job.id, ack_all=True
        )
        if blocking:
            print("NO_FORMAL still blocking")
        else:
            job = await att_service.confirm(session, principal, job.id)
            formal = await att_service.export_formal(session, principal, job.id)
            (OUT / "formal.xlsx").write_bytes(formal)
            print("FORMAL_OK", len(formal), job.status)

        sample = []
        for person in (job.compute_result or {}).get("people") or []:
            sample.append(
                {
                    "name": person.get("name") or person.get("person_name"),
                    "tallies": person.get("tallies") or person.get("red_box"),
                }
            )
        (OUT / "sample_people.json").write_text(
            json.dumps(sample[:20], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("OUT", OUT)


if __name__ == "__main__":
    asyncio.run(main())
