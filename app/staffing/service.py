"""Staffing import / confirm / void / summary services."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger, log_event, preview_text, timed_event
from app.identity.principal import Principal
from app.models.entity import AuditEvent, new_id
from app.models.identity import Project
from app.models.staffing import StaffingAttendanceFact, StaffingImportBatch
from app.staffing.match import match_project, match_to_dict
from app.staffing.parse import parse_daily_report, parse_result_to_dict
from app.staffing.stints import build_stints, format_stints_summary

logger = get_logger("staffing")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _actor(principal: Principal) -> str:
    return principal.username or principal.user_id


async def _add_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict | None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )


async def ensure_project_access(principal: Principal, project_id: str) -> None:
    if project_id in principal.project_ids:
        return
    if "projects:manage" in principal.permissions:
        return
    raise AppError("无权访问该项目", status_code=403)


async def create_import_batch(
    session: AsyncSession,
    *,
    principal: Principal,
    filename: str,
    data: bytes,
    storage_key: str,
    batch_id: str | None = None,
) -> StaffingImportBatch:
    with timed_event(logger, "staffing.import.parse") as meta:
        result = parse_daily_report(data, filename=filename)
        meta["row_count"] = len(result.rows)
        meta["warning_count"] = len(result.warnings)
        meta["filename"] = preview_text(filename, limit=80)

    with timed_event(logger, "staffing.import.match_project") as meta:
        match = await match_project(
            session,
            principal.tenant_id,
            principal.project_ids,
            result.filename_codes,
        )
        meta["status"] = match.status
        meta["codes"] = result.filename_codes

    from dataclasses import asdict

    warnings = [asdict(w) for w in result.warnings]

    needs_review = bool(warnings) or match.status != "matched"
    if match.status == "unmatched":
        warnings.append(
            {
                "code": "project_unmatched",
                "message": "未能从文件名/标题匹配到已授权项目",
                "row": None,
                "detail": {"codes": result.filename_codes},
            }
        )
        needs_review = True
    elif match.status == "ambiguous":
        warnings.append(
            {
                "code": "project_ambiguous",
                "message": "匹配到多个已授权项目，需人工选定",
                "row": None,
                "detail": {"candidates": match.candidates},
            }
        )
        needs_review = True

    batch = StaffingImportBatch(
        id=batch_id or new_id(),
        tenant_id=principal.tenant_id,
        project_id=match.project_id,
        status="needs_review" if needs_review else "parsed",
        filename=filename,
        storage_key=storage_key,
        uploaded_by=principal.user_id,
        warnings=warnings,
        parse_result=parse_result_to_dict(result),
        resolved_warnings={},
        match_info=match_to_dict(match),
    )
    session.add(batch)
    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="staffing.import",
        resource_type="staffing_batch",
        resource_id=batch.id,
        detail={
            "filename": filename,
            "warning_count": len(warnings),
            "match": match.status,
            "person_days": len(result.rows),
        },
    )
    await session.commit()
    await session.refresh(batch)

    if needs_review:
        log_event(
            logger,
            "staffing.review.pending",
            event="staffing.review.pending",
            batch_id=batch.id,
            issue_codes=sorted({w["code"] for w in warnings}),
        )
    return batch


async def get_batch(
    session: AsyncSession, tenant_id: str, batch_id: str
) -> StaffingImportBatch:
    batch = await session.get(StaffingImportBatch, batch_id)
    if batch is None or batch.tenant_id != tenant_id:
        raise NotFoundError("导入批次不存在")
    return batch


async def review_batch(
    session: AsyncSession,
    *,
    principal: Principal,
    batch_id: str,
    project_id: str | None = None,
    resolutions: dict[str, Any] | None = None,
    person_renames: dict[str, str] | None = None,
) -> StaffingImportBatch:
    batch = await get_batch(session, principal.tenant_id, batch_id)
    if batch.status in {"confirmed", "voided"}:
        raise AppError("已确认或已作废的批次不可再复核", status_code=409)

    if project_id:
        await ensure_project_access(principal, project_id)
        proj = await session.get(Project, project_id)
        if proj is None or proj.tenant_id != principal.tenant_id:
            raise AppError("项目不存在", status_code=404)
        batch.project_id = project_id

    resolved = dict(batch.resolved_warnings or {})
    if resolutions:
        resolved.update(resolutions)
    batch.resolved_warnings = resolved

    if person_renames and batch.parse_result:
        rows = batch.parse_result.get("rows") or []
        for row in rows:
            old = row.get("person_name")
            if old in person_renames:
                row["person_name"] = person_renames[old]
        batch.parse_result = {**batch.parse_result, "rows": rows}

    # Determine remaining open warnings
    open_codes = _open_warning_codes_from(batch.warnings or [], resolved, batch.project_id)

    if batch.project_id and not open_codes:
        batch.status = "parsed"
    else:
        batch.status = "needs_review"

    await _add_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=_actor(principal),
        action="staffing.review.resolve",
        resource_type="staffing_batch",
        resource_id=batch.id,
        detail={"project_id": batch.project_id, "resolved": list(resolved.keys())},
    )
    await session.commit()
    await session.refresh(batch)
    return batch


def _collision_resolutions(resolved: dict[str, Any]) -> dict[str, Any]:
    raw = resolved.get("name_kind_collision")
    return raw if isinstance(raw, dict) else {}


def _is_collision_resolved(warnings: list, resolved: dict[str, Any]) -> bool:
    collisions = [
        w
        for w in warnings
        if isinstance(w, dict) and w.get("code") == "name_kind_collision"
    ]
    if not collisions:
        return True
    by_name = _collision_resolutions(resolved)
    for w in collisions:
        detail = w.get("detail") if isinstance(w.get("detail"), dict) else {}
        name = detail.get("person_name")
        entry = by_name.get(name) if name else None
        if not isinstance(entry, dict):
            return False
        action = entry.get("action")
        if action == "split":
            continue
        if action == "merge" and entry.get("keep_kind") in {
            "internal_formal",
            "internal_contract",
        }:
            continue
        return False
    return True


def _open_warning_codes_from(
    warnings: list, resolved: dict[str, Any], project_id: str | None
) -> set[str]:
    open_codes: set[str] = set()
    for w in warnings:
        if not isinstance(w, dict):
            continue
        code = w.get("code")
        if not code:
            continue
        if code in {"project_unmatched", "project_ambiguous"} and project_id:
            continue
        if code == "name_kind_collision":
            if not _is_collision_resolved(warnings, resolved):
                open_codes.add(code)
            continue
        if code not in resolved:
            open_codes.add(code)
    return open_codes


def _open_warning_codes(batch: StaffingImportBatch) -> set[str]:
    return _open_warning_codes_from(
        batch.warnings or [],
        batch.resolved_warnings or {},
        batch.project_id,
    )


def _rows_after_collision_resolution(
    rows: list[dict[str, Any]], resolved: dict[str, Any]
) -> list[dict[str, Any]]:
    by_name = _collision_resolutions(resolved)
    out: list[dict[str, Any]] = []
    for r in rows:
        name = r.get("person_name")
        kind = r.get("person_kind") or "internal_formal"
        entry = by_name.get(name) if name else None
        if isinstance(entry, dict) and entry.get("action") == "merge":
            if kind != entry.get("keep_kind"):
                continue
        out.append(r)
    return out


async def confirm_batch(
    session: AsyncSession, *, principal: Principal, batch_id: str
) -> StaffingImportBatch:
    batch = await get_batch(session, principal.tenant_id, batch_id)
    if batch.status == "confirmed":
        raise AppError("批次已确认", status_code=409)
    if batch.status == "voided":
        raise AppError("批次已作废", status_code=409)
    if not batch.project_id:
        raise AppError("请先选定项目后再确认", status_code=400)
    await ensure_project_access(principal, batch.project_id)
    open_codes = _open_warning_codes(batch)
    if open_codes:
        raise AppError(
            f"仍有未决议告警：{', '.join(sorted(open_codes))}",
            status_code=400,
        )

    rows = _rows_after_collision_resolution(
        list((batch.parse_result or {}).get("rows") or []),
        batch.resolved_warnings or {},
    )
    dates = {r["work_date"] for r in rows}
    date_objs = [date.fromisoformat(d) for d in dates]

    with timed_event(logger, "staffing.import.confirm") as meta:
        voided = 0
        if date_objs:
            existing = (
                await session.execute(
                    select(StaffingAttendanceFact).where(
                        StaffingAttendanceFact.tenant_id == principal.tenant_id,
                        StaffingAttendanceFact.project_id == batch.project_id,
                        StaffingAttendanceFact.status == "active",
                        StaffingAttendanceFact.work_date.in_(date_objs),
                    )
                )
            ).scalars().all()
            for fact in existing:
                fact.status = "voided"
                fact.void_reason = "superseded_by_batch"
                fact.voided_by = principal.user_id
                fact.voided_at = _utcnow()
                voided += 1

        # dedupe by date + person + kind
        seen: set[tuple[str, str, str]] = set()
        written = 0
        for r in rows:
            kind = r.get("person_kind") or "internal_formal"
            key = (r["work_date"], r["person_name"], kind)
            if key in seen:
                continue
            seen.add(key)
            session.add(
                StaffingAttendanceFact(
                    tenant_id=principal.tenant_id,
                    project_id=batch.project_id,
                    batch_id=batch.id,
                    work_date=date.fromisoformat(r["work_date"]),
                    person_name=r["person_name"],
                    person_kind=kind,
                    status="active",
                    stage=r.get("stage"),
                    source_row=r.get("source_row"),
                )
            )
            written += 1

        batch.status = "confirmed"
        batch.confirmed_at = _utcnow()
        batch.confirmed_by = principal.user_id
        meta["facts_written"] = written
        meta["dates_voided_overlap"] = voided
        meta["batch_id"] = batch.id

        await _add_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=_actor(principal),
            action="staffing.confirm",
            resource_type="staffing_batch",
            resource_id=batch.id,
            detail={
                "project_id": batch.project_id,
                "facts_written": written,
                "dates_voided_overlap": voided,
            },
        )
        await session.commit()
        await session.refresh(batch)
    return batch


KIND_LABEL = {
    "internal_formal": "正式我司",
    "internal_contract": "我司·外包性质",
}

# Formal first, then contract; within kind by name.
_KIND_SORT = {"internal_formal": 0, "internal_contract": 1}


async def project_summary(
    session: AsyncSession, *, principal: Principal, project_id: str
) -> dict[str, Any]:
    await ensure_project_access(principal, project_id)
    proj = await session.get(Project, project_id)
    facts = (
        await session.execute(
            select(StaffingAttendanceFact).where(
                StaffingAttendanceFact.tenant_id == principal.tenant_id,
                StaffingAttendanceFact.project_id == project_id,
                StaffingAttendanceFact.status == "active",
            )
        )
    ).scalars().all()

    by_person: dict[tuple[str, str], dict[str, Any]] = {}
    for f in facts:
        key = (f.person_name, f.person_kind)
        entry = by_person.setdefault(
            key,
            {
                "person_name": f.person_name,
                "person_kind": f.person_kind,
                "dates": set(),
            },
        )
        entry["dates"].add(f.work_date.isoformat())

    people = []
    all_dates: set[str] = set()
    by_kind_days: dict[str, set[str]] = {
        "internal_formal": set(),
        "internal_contract": set(),
    }
    by_kind_people: dict[str, set[str]] = {
        "internal_formal": set(),
        "internal_contract": set(),
    }
    person_day_total = 0
    for (name, kind), entry in sorted(
        by_person.items(),
        key=lambda item: (_KIND_SORT.get(item[0][1], 9), item[0][0]),
    ):
        dates = sorted(entry["dates"])
        person_day_total += len(dates)
        all_dates.update(dates)
        by_kind_people.setdefault(kind, set()).add(name)
        # person-days per kind: count this person's days under this kind
        by_kind_days.setdefault(kind, set())
        # use synthetic keys for person-day totals per kind
        for d in dates:
            by_kind_days[kind].add(f"{name}:{d}")
        stints = build_stints(dates)
        people.append(
            {
                "person_name": name,
                "person_kind": kind,
                "person_kind_label": KIND_LABEL.get(kind, kind),
                "days_on_site": len(dates),
                "dates": dates,
                "stint_count": len(stints),
                "stints": stints,
            }
        )

    sorted_dates = sorted(all_dates)
    return {
        "project_id": project_id,
        "project_code": proj.code if proj else "",
        "project_name": proj.name if proj else "",
        "people": people,
        "person_count": len(people),
        "person_day_total": person_day_total,
        "date_from": sorted_dates[0] if sorted_dates else None,
        "date_to": sorted_dates[-1] if sorted_dates else None,
        "by_kind": {
            "formal": {
                "person_count": len(by_kind_people.get("internal_formal") or ()),
                "person_day_total": len(by_kind_days.get("internal_formal") or ()),
            },
            "contract": {
                "person_count": len(by_kind_people.get("internal_contract") or ()),
                "person_day_total": len(by_kind_days.get("internal_contract") or ()),
            },
        },
        "label": "在场天数",
    }


async def list_facts(
    session: AsyncSession,
    *,
    principal: Principal,
    project_id: str,
    include_voided: bool = False,
) -> list[StaffingAttendanceFact]:
    await ensure_project_access(principal, project_id)
    stmt = select(StaffingAttendanceFact).where(
        StaffingAttendanceFact.tenant_id == principal.tenant_id,
        StaffingAttendanceFact.project_id == project_id,
    )
    if not include_voided:
        stmt = stmt.where(StaffingAttendanceFact.status == "active")
    stmt = stmt.order_by(StaffingAttendanceFact.work_date, StaffingAttendanceFact.person_name)
    return list((await session.execute(stmt)).scalars().all())


async def void_facts(
    session: AsyncSession,
    *,
    principal: Principal,
    project_id: str,
    scope: str,
    dates: list[str] | None = None,
    person_names: list[str] | None = None,
    batch_id: str | None = None,
) -> int:
    await ensure_project_access(principal, project_id)
    stmt = select(StaffingAttendanceFact).where(
        StaffingAttendanceFact.tenant_id == principal.tenant_id,
        StaffingAttendanceFact.project_id == project_id,
        StaffingAttendanceFact.status == "active",
    )

    action = "staffing.void.day_person"
    if scope == "person":
        if not person_names:
            raise AppError("按人作废需要 person_names", status_code=400)
        stmt = stmt.where(StaffingAttendanceFact.person_name.in_(person_names))
        action = "staffing.void.person"
    elif scope == "batch":
        if not batch_id:
            raise AppError("按批作废需要 batch_id", status_code=400)
        stmt = stmt.where(StaffingAttendanceFact.batch_id == batch_id)
        action = "staffing.void.batch"
    elif scope == "day_person":
        if not dates or not person_names:
            raise AppError("按日×人作废需要 dates 与 person_names", status_code=400)
        stmt = stmt.where(
            StaffingAttendanceFact.work_date.in_([date.fromisoformat(d) for d in dates]),
            StaffingAttendanceFact.person_name.in_(person_names),
        )
        action = "staffing.void.day_person"
    elif scope == "day":
        if not dates:
            raise AppError("按日作废需要 dates", status_code=400)
        stmt = stmt.where(
            StaffingAttendanceFact.work_date.in_([date.fromisoformat(d) for d in dates])
        )
        action = "staffing.void.day"
    else:
        raise AppError(f"未知作废范围: {scope}", status_code=400)

    with timed_event(logger, "staffing.void") as meta:
        facts = list((await session.execute(stmt)).scalars().all())
        now = _utcnow()
        for f in facts:
            f.status = "voided"
            f.void_reason = f"void_{scope}"
            f.voided_by = principal.user_id
            f.voided_at = now
        if scope == "batch" and batch_id:
            batch = await get_batch(session, principal.tenant_id, batch_id)
            if batch.status == "confirmed":
                batch.status = "voided"
        meta["scope"] = scope
        meta["count"] = len(facts)
        meta["project_id"] = project_id

        await _add_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=_actor(principal),
            action=action,
            resource_type="project",
            resource_id=project_id,
            detail={
                "scope": scope,
                "count": len(facts),
                "dates": dates,
                "person_names": person_names,
                "batch_id": batch_id,
            },
        )
        await session.commit()
    return len(facts)


async def export_project_xlsx(
    session: AsyncSession, *, principal: Principal, project_id: str
) -> bytes:
    """Build workbook with 汇总 + 工期段 + 明细 sheets for an authorized project."""
    import io

    from openpyxl import Workbook

    summary = await project_summary(session, principal=principal, project_id=project_id)
    facts = await list_facts(
        session, principal=principal, project_id=project_id, include_voided=False
    )
    people = list(summary.get("people") or [])
    max_stints = max(
        (len(p.get("stints") or []) or int(p.get("stint_count") or 0) for p in people),
        default=0,
    )
    emit_numbered = 0 < max_stints <= 5

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "汇总"
    ws_sum.append(
        [
            "项目编号",
            summary.get("project_code") or "",
            "项目名称",
            summary.get("project_name") or "",
        ]
    )
    ws_sum.append(
        [
            "日期起",
            summary.get("date_from") or "",
            "日期止",
            summary.get("date_to") or "",
        ]
    )
    ws_sum.append(
        [
            "人数",
            summary.get("person_count") or 0,
            "人天合计",
            summary.get("person_day_total") or 0,
        ]
    )
    by_kind = summary.get("by_kind") or {}
    formal = by_kind.get("formal") or {}
    contract = by_kind.get("contract") or {}
    ws_sum.append(
        [
            "正式人数",
            formal.get("person_count") or 0,
            "正式人天",
            formal.get("person_day_total") or 0,
        ]
    )
    ws_sum.append(
        [
            "外包性质人数",
            contract.get("person_count") or 0,
            "外包性质人天",
            contract.get("person_day_total") or 0,
        ]
    )
    ws_sum.append([])
    header = ["姓名", "身份", "在场天数", "进场次数", "在场摘要"]
    if emit_numbered:
        for i in range(1, max_stints + 1):
            header.extend([f"第{i}段入", f"第{i}段出", f"第{i}段天数"])
    ws_sum.append(header)
    for p in people:
        stints = list(p.get("stints") or [])
        if not stints and p.get("dates"):
            stints = build_stints(list(p.get("dates") or []))
        stint_count = len(stints) or int(p.get("stint_count") or 0)
        row = [
            p.get("person_name"),
            p.get("person_kind_label") or KIND_LABEL.get(p.get("person_kind"), ""),
            p.get("days_on_site"),
            stint_count,
            format_stints_summary(stints),
        ]
        if emit_numbered:
            for i in range(1, max_stints + 1):
                s = stints[i - 1] if i <= len(stints) else None
                row.extend(
                    [
                        (s or {}).get("entry_date") or "",
                        (s or {}).get("exit_date") or "",
                        (s or {}).get("days") or "",
                    ]
                )
        ws_sum.append(row)

    ws_stint = wb.create_sheet("工期段")
    ws_stint.append(
        ["姓名", "身份", "第几次进场", "入场日", "离场日", "本段天数", "累计在场天数"]
    )
    for p in people:
        stints = list(p.get("stints") or [])
        if not stints and p.get("dates"):
            stints = build_stints(list(p.get("dates") or []))
        kind_label = p.get("person_kind_label") or KIND_LABEL.get(
            p.get("person_kind"), ""
        )
        if not stints:
            ws_stint.append(
                [
                    p.get("person_name"),
                    kind_label,
                    "",
                    "",
                    "",
                    "",
                    p.get("days_on_site") or 0,
                ]
            )
            continue
        for s in stints:
            ws_stint.append(
                [
                    p.get("person_name"),
                    kind_label,
                    s.get("index"),
                    s.get("entry_date"),
                    s.get("exit_date"),
                    s.get("days"),
                    p.get("days_on_site") or 0,
                ]
            )

    ws_detail = wb.create_sheet("明细")
    ws_detail.append(["工作日", "姓名", "身份"])
    sorted_facts = sorted(
        facts,
        key=lambda f: (
            _KIND_SORT.get(f.person_kind, 9),
            f.person_name,
            f.work_date,
        ),
    )
    for f in sorted_facts:
        ws_detail.append(
            [
                f.work_date.isoformat(),
                f.person_name,
                KIND_LABEL.get(f.person_kind, f.person_kind),
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
